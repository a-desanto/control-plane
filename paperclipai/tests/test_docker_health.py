"""Container built from Dockerfile starts and GET /health returns 200."""

import subprocess
import time
import uuid

import httpx
import pytest


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="Docker daemon not available"
)

IMAGE_TAG = f"paperclipai-ci-test:{uuid.uuid4().hex[:8]}"
CONTAINER_NAME = f"paperclipai-ci-{uuid.uuid4().hex[:8]}"
HOST_PORT = 18765


@pytest.fixture(scope="module")
def built_image():
    paperclipai_dir = (
        __import__("pathlib").Path(__file__).parent.parent
    )
    result = subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "."],
        cwd=paperclipai_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        pytest.fail(f"docker build failed:\n{result.stdout}\n{result.stderr}")
    yield IMAGE_TAG
    subprocess.run(["docker", "rmi", "-f", IMAGE_TAG], capture_output=True)


@pytest.fixture(scope="module")
def running_container(built_image):
    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", CONTAINER_NAME,
            "-p", f"{HOST_PORT}:8000",
            built_image,
        ],
        check=True,
        capture_output=True,
    )
    # Give the server a moment to start
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://localhost:{HOST_PORT}/health", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(1)
    yield CONTAINER_NAME
    subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)


def test_health_returns_200(running_container) -> None:
    r = httpx.get(f"http://localhost:{HOST_PORT}/health", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
