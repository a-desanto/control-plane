SCHEMAS := schemas/intent@v3.2.json \
           schemas/workflow_plan@v3.2.json \
           schemas/execution_instruction@v3.2.json \
           schemas/tool_output@v3.2.json

CONTRACTS_DIR := paperclipai/app/contracts

CODEGEN_OPTS := \
  --input-file-type jsonschema \
  --output-model-type pydantic_v2.BaseModel \
  --use-schema-description \
  --target-python-version 3.12 \
  --formatters ruff-format ruff-check

.PHONY: codegen codegen-check test

codegen:
	cd paperclipai && \
	uv run datamodel-codegen \
	  --input ../schemas/intent@v3.2.json \
	  --output app/contracts/intent.py \
	  $(CODEGEN_OPTS) && \
	uv run datamodel-codegen \
	  --input ../schemas/workflow_plan@v3.2.json \
	  --output app/contracts/workflow_plan.py \
	  $(CODEGEN_OPTS) && \
	uv run datamodel-codegen \
	  --input ../schemas/execution_instruction@v3.2.json \
	  --output app/contracts/execution_instruction.py \
	  $(CODEGEN_OPTS) && \
	uv run datamodel-codegen \
	  --input ../schemas/tool_output@v3.2.json \
	  --output app/contracts/tool_output.py \
	  $(CODEGEN_OPTS)

codegen-check:
	$(MAKE) codegen
	git diff --exit-code $(CONTRACTS_DIR)/

test:
	cd paperclipai && uv run pytest tests/ -v
