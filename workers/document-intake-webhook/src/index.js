/**
 * document-intake-webhook
 *
 * Handles SNS → S3 event notifications at POST /api/webhooks/document-intake.
 *
 * Two intake paths:
 *
 *   Path 1 — S3 drop (direct upload)
 *     Object key NOT in inbox/ or email-attachments/ → source_type='s3_drop'
 *
 *   Path 2 — Email forwarding via SES
 *     inbox/<message-id>     → fetch .eml, parse MIME, extract attachments,
 *                               upload each to email-attachments/<msg-id>/<name>,
 *                               create document_intake rows (source_type='email_forwarded')
 *     email-attachments/<…>  → skip (row already created by email handler above)
 */

import express from 'express';
import pg from 'pg';
import https from 'node:https';
import http from 'node:http';
import crypto from 'node:crypto';
import path from 'node:path';
import pino from 'pino';
import pinoHttp from 'pino-http';
import { S3Client, GetObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';
import { simpleParser } from 'mailparser';

const log = pino({ level: process.env.LOG_LEVEL ?? 'info' });

// ── Config ────────────────────────────────────────────────────────────────────
const PORT           = parseInt(process.env.PORT ?? '4010', 10);
const CKDB_URL       = process.env.CKDB_URL;
const SNS_VERIFY_SIG = process.env.SNS_SKIP_SIGNATURE_VERIFY !== 'true';
const AWS_REGION     = process.env.AWS_REGION ?? 'us-east-2';
const AWS_KEY        = process.env.AWS_ACCESS_KEY_ID;
const AWS_SECRET     = process.env.AWS_SECRET_ACCESS_KEY;

if (!CKDB_URL) {
  log.error('CKDB_URL environment variable is required');
  process.exit(1);
}
if (!AWS_KEY || !AWS_SECRET) {
  log.warn('AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY not set — email intake (S3 fetch) will fail');
}

// ── Clients ───────────────────────────────────────────────────────────────────
const pool = new pg.Pool({ connectionString: CKDB_URL, max: 5 });

const s3 = new S3Client({
  region: AWS_REGION,
  credentials: AWS_KEY ? { accessKeyId: AWS_KEY, secretAccessKey: AWS_SECRET } : undefined,
});

// ── SNS certificate cache ─────────────────────────────────────────────────────
const certCache = new Map();

async function fetchText(url) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    mod.get(url, (res) => {
      let body = '';
      res.on('data', (d) => { body += d; });
      res.on('end', () => resolve(body));
      res.on('error', reject);
    }).on('error', reject);
  });
}

function assertValidCertUrl(url) {
  let parsed;
  try { parsed = new URL(url); } catch { throw new Error('Invalid SigningCertURL'); }
  if (parsed.protocol !== 'https:') throw new Error('SigningCertURL must be HTTPS');
  if (!/^sns\.[a-z0-9-]+\.amazonaws\.com$/.test(parsed.hostname)) {
    throw new Error(`Untrusted SigningCertURL hostname: ${parsed.hostname}`);
  }
}

function buildSigningString(msg) {
  const fields =
    msg.Type === 'Notification'
      ? ['Message', 'MessageId', 'Subject', 'Timestamp', 'TopicArn', 'Type']
      : ['Message', 'MessageId', 'SubscribeURL', 'Timestamp', 'Token', 'TopicArn', 'Type'];
  return fields
    .filter((f) => msg[f] !== undefined)
    .map((f) => `${f}\n${msg[f]}\n`)
    .join('');
}

async function verifySnsSignature(msg) {
  if (!SNS_VERIFY_SIG) return;
  assertValidCertUrl(msg.SigningCertURL);
  let cert = certCache.get(msg.SigningCertURL);
  if (!cert) {
    cert = await fetchText(msg.SigningCertURL);
    certCache.set(msg.SigningCertURL, cert);
  }
  const sigBuffer = Buffer.from(msg.Signature, 'base64');
  const toSign    = buildSigningString(msg);
  const verify    = crypto.createVerify('SHA1');
  verify.update(toSign, 'utf8');
  if (!verify.verify(cert, sigBuffer)) throw new Error('SNS signature verification failed');
}

// ── DB helpers ────────────────────────────────────────────────────────────────
async function resolveCompanyId(bucketName) {
  const row = await pool.query(
    'SELECT company_id FROM bucket_company_map WHERE bucket_name = $1',
    [bucketName]
  );
  return row.rows[0]?.company_id ?? null;
}

async function insertDocumentIntake({ companyId, sourceType, sourceUri, rawPdfS3Key, notes }) {
  const { rows } = await pool.query(
    `INSERT INTO document_intake
       (company_id, source_type, source_uri, raw_pdf_s3_key, status, notes)
     VALUES ($1, $2, $3, $4, 'received', $5)
     RETURNING id`,
    [companyId, sourceType, sourceUri, rawPdfS3Key, notes ? JSON.stringify(notes) : null]
  );
  return rows[0].id;
}

// ── S3 helpers ────────────────────────────────────────────────────────────────
async function s3GetBuffer(bucket, key) {
  const resp = await s3.send(new GetObjectCommand({ Bucket: bucket, Key: key }));
  const chunks = [];
  for await (const chunk of resp.Body) chunks.push(chunk);
  return Buffer.concat(chunks);
}

async function s3Put(bucket, key, body, contentType) {
  await s3.send(new PutObjectCommand({
    Bucket: bucket,
    Key: key,
    Body: body,
    ContentType: contentType,
  }));
}

// ── Object key routing ────────────────────────────────────────────────────────
// 'email'            → SES-delivered raw .eml; parse and extract attachments
// 'email-attachment' → already handled by the email handler; skip
// 's3_drop'          → direct client upload; create intake row
function prefixType(objectKey) {
  if (objectKey.startsWith('inbox/'))             return 'email';
  if (objectKey.startsWith('email-attachments/')) return 'email-attachment';
  return 's3_drop';
}

// ── MIME attachment filter ─────────────────────────────────────────────────────
// Accept document-like attachments; reject inline images, auto-reply bodies, etc.
const ACCEPTED_MIME_PREFIXES = [
  'application/pdf',
  'application/vnd.ms-excel',
  'application/vnd.openxmlformats-officedocument',
  'application/msword',
  'application/vnd.ms-powerpoint',
  'application/zip',
  'image/',            // scanned receipts, photos of invoices
  'text/plain',        // occasionally structured text reports
  'text/csv',
];

function isAcceptedAttachment(att) {
  if (att.contentDisposition === 'inline') return false;  // skip inline images
  const ct = (att.contentType ?? '').toLowerCase();
  return ACCEPTED_MIME_PREFIXES.some((p) => ct.startsWith(p));
}

function safeFilename(raw, index) {
  // Strip path components, collapse whitespace, fall back to attachment-N
  const name = (raw ?? '').replace(/[/\\]/g, '_').replace(/\s+/g, '_').trim();
  return name || `attachment-${index}`;
}

// ── Email handler ─────────────────────────────────────────────────────────────
async function handleEmail(bucketName, objectKey, companyId) {
  log.info({ bucketName, objectKey }, 'email.intake.start');

  // objectKey = inbox/<message-id>
  const messageId = path.basename(objectKey);

  // Fetch raw .eml from S3
  let emlBuffer;
  try {
    emlBuffer = await s3GetBuffer(bucketName, objectKey);
  } catch (err) {
    log.error({ err: err.message, objectKey }, 'email.s3_fetch_failed');
    throw err;
  }

  // Parse MIME
  let parsed;
  try {
    parsed = await simpleParser(emlBuffer);
  } catch (err) {
    log.error({ err: err.message }, 'email.parse_failed');
    throw err;
  }

  const sender   = parsed.from?.text ?? 'unknown';
  const subject  = parsed.subject ?? '(no subject)';
  const sentDate = parsed.date?.toISOString() ?? null;
  const bodyText = (parsed.text ?? '').slice(0, 500); // excerpt for notes

  const notes = { sender, subject, sent_date: sentDate, body_excerpt: bodyText, message_id: messageId };

  const attachments = (parsed.attachments ?? []).filter(isAcceptedAttachment);

  if (attachments.length === 0) {
    log.info({ sender, subject }, 'email.no_attachments — skipping');
    return 0;
  }

  let processed = 0;
  for (let i = 0; i < attachments.length; i++) {
    const att      = attachments[i];
    const filename = safeFilename(att.filename, i);
    const s3Key    = `email-attachments/${messageId}/${filename}`;
    const sourceUri = `${sender} → ${subject} / ${filename}`;

    try {
      await s3Put(bucketName, s3Key, att.content, att.contentType ?? 'application/octet-stream');
      log.info({ s3Key, size: att.content.length }, 'email.attachment.uploaded');
    } catch (err) {
      log.error({ err: err.message, s3Key }, 'email.attachment.upload_failed');
      continue;
    }

    try {
      const id = await insertDocumentIntake({
        companyId,
        sourceType: 'email_forwarded',
        sourceUri,
        rawPdfS3Key: s3Key,
        notes,
      });
      log.info({ id, s3Key, sourceUri }, 'email.document_intake.created');
      processed++;
    } catch (err) {
      log.error({ err: err.message, s3Key }, 'email.document_intake.insert_failed');
    }
  }

  return processed;
}

// ── Express app ────────────────────────────────────────────────────────────────
const app = express();

app.use((req, _res, next) => {
  let data = [];
  req.on('data', (chunk) => data.push(chunk));
  req.on('end', () => {
    req.rawBody = Buffer.concat(data);
    try { req.body = JSON.parse(req.rawBody.toString('utf8')); }
    catch { req.body = {}; }
    next();
  });
});

app.use(pinoHttp({ logger: log }));

app.get('/api/webhooks/document-intake/health', (_req, res) => {
  res.json({ ok: true, service: 'document-intake-webhook', version: '1.1.0' });
});

app.post('/api/webhooks/document-intake', async (req, res) => {
  const msg     = req.body;
  const msgType = req.headers['x-amz-sns-message-type'];

  if (!msgType) {
    log.warn('Missing x-amz-sns-message-type header');
    return res.status(400).json({ error: 'Missing SNS message type header' });
  }

  try {
    await verifySnsSignature(msg);
  } catch (err) {
    log.error({ err: err.message }, 'SNS signature verification failed');
    return res.status(403).json({ error: 'Signature verification failed' });
  }

  // ── SubscriptionConfirmation ───────────────────────────────────────────────
  if (msgType === 'SubscriptionConfirmation') {
    log.info({ subscribeUrl: msg.SubscribeURL }, 'SNS SubscriptionConfirmation received — confirming');
    try {
      await fetchText(msg.SubscribeURL);
      log.info('SNS subscription confirmed');
      return res.status(200).json({ confirmed: true });
    } catch (err) {
      log.error({ err: err.message }, 'Failed to confirm SNS subscription');
      return res.status(500).json({ error: 'Subscription confirmation failed' });
    }
  }

  if (msgType === 'UnsubscribeConfirmation') {
    log.info('SNS UnsubscribeConfirmation received — ignored');
    return res.status(200).json({ ok: true });
  }

  if (msgType !== 'Notification') {
    log.warn({ msgType }, 'Unknown SNS message type');
    return res.status(400).json({ error: `Unknown message type: ${msgType}` });
  }

  // ── Notification ───────────────────────────────────────────────────────────
  let s3Event;
  try {
    s3Event = typeof msg.Message === 'string' ? JSON.parse(msg.Message) : msg.Message;
  } catch (err) {
    log.error({ err: err.message }, 'Failed to parse S3 event from SNS message');
    return res.status(400).json({ error: 'Invalid S3 event payload' });
  }

  const records = s3Event?.Records ?? [];
  if (records.length === 0) {
    log.info('SNS Notification with no S3 records (test event) — acknowledged');
    return res.status(200).json({ ok: true, processed: 0 });
  }

  let processed = 0;
  for (const record of records) {
    if (record.eventSource !== 'aws:s3') continue;

    const bucketName = record.s3?.bucket?.name;
    const objectKey  = record.s3?.object?.key
      ? decodeURIComponent(record.s3.object.key.replace(/\+/g, ' '))
      : null;

    if (!bucketName || !objectKey) {
      log.warn({ record }, 'S3 record missing bucket or key — skipping');
      continue;
    }
    if (objectKey.endsWith('/')) {
      log.debug({ objectKey }, 'Skipping directory placeholder');
      continue;
    }

    const companyId = await resolveCompanyId(bucketName);
    if (!companyId) {
      log.error({ bucketName }, 'No company_id mapping for bucket — skipping');
      continue;
    }

    const type = prefixType(objectKey);

    if (type === 'email-attachment') {
      // Row already created by handleEmail when it uploaded this object.
      log.debug({ objectKey }, 'email-attachment object — row already created, skipping');
      continue;
    }

    if (type === 'email') {
      try {
        const n = await handleEmail(bucketName, objectKey, companyId);
        processed += n;
      } catch (err) {
        log.error({ err: err.message, objectKey }, 'handleEmail failed');
        return res.status(500).json({ error: 'Email processing failed' });
      }
      continue;
    }

    // type === 's3_drop'
    const sourceUri = `s3://${bucketName}/${objectKey}`;
    try {
      const id = await insertDocumentIntake({
        companyId,
        sourceType: 's3_drop',
        sourceUri,
        rawPdfS3Key: objectKey,
        notes: null,
      });
      log.info({ id, companyId, sourceUri }, 'document_intake row created');
      processed++;
    } catch (err) {
      log.error({ err: err.message, companyId, sourceUri }, 'Failed to insert document_intake row');
      return res.status(500).json({ error: 'Database insert failed' });
    }
  }

  return res.status(200).json({ ok: true, processed });
});

app.use((_req, res) => res.status(404).json({ error: 'Not found' }));

// ── Start ─────────────────────────────────────────────────────────────────────
pool.connect()
  .then((client) => {
    client.release();
    log.info('Database connection verified');
    app.listen(PORT, '0.0.0.0', () => {
      log.info({ port: PORT }, 'document-intake-webhook listening');
    });
  })
  .catch((err) => {
    log.error({ err: err.message }, 'Failed to connect to database — exiting');
    process.exit(1);
  });
