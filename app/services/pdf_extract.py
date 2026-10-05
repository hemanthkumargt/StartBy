"""Text extraction from an untrusted PDF, run in a throw-away child process.

pypdf has no cap on how far a compressed stream may expand: a ~100 KB PDF can
inflate to tens of MB and take over 2 GB of RAM and 40 s of CPU while being
parsed, which on a 1 GB VM would take down the web worker. So extraction runs
as `python -m app.services.pdf_extract` with hard RLIMIT_AS / RLIMIT_CPU set
by the child on itself, a wall-clock timeout from the parent, and output
capped at the capture text limit. A bomb kills only the child.

Protocol: PDF bytes on stdin; extracted text on stdout; exit code 0 = ok,
3 = password protected, anything else = unreadable/too expensive."""

import subprocess
import sys

from app.constants import CAPTURE_PDF_MAX_PAGES, CAPTURE_TEXT_MAX_CHARS

MEMORY_LIMIT_BYTES = 400 * 1024 * 1024
CPU_LIMIT_SECONDS = 8
WALL_TIMEOUT_SECONDS = 15
EXIT_ENCRYPTED = 3


class PdfEncrypted(Exception):
    pass


class PdfUnreadable(Exception):
    pass


def extract_text(
    data: bytes,
    *,
    memory_limit: int = MEMORY_LIMIT_BYTES,
    cpu_limit: int = CPU_LIMIT_SECONDS,
) -> str:
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell, no user input in it
            [sys.executable, "-m", "app.services.pdf_extract", str(memory_limit), str(cpu_limit)],
            input=data,
            capture_output=True,
            timeout=WALL_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfUnreadable("PDF took too long to read") from exc
    if proc.returncode == EXIT_ENCRYPTED:
        raise PdfEncrypted()
    if proc.returncode != 0:
        raise PdfUnreadable(f"extractor exited with {proc.returncode}")
    return proc.stdout.decode("utf-8", errors="replace")


def _child_main() -> int:
    import io

    memory_limit, cpu_limit = int(sys.argv[1]), int(sys.argv[2])
    try:
        import resource
    except ImportError:
        resource = None
    if resource is not None:
        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
        except (ValueError, OSError):
            # macOS refuses RLIMIT_AS; the parent's wall-clock timeout still applies.
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit + 1))
        except (ValueError, OSError):
            # Windows does not expose POSIX resource limits.
            pass

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(sys.stdin.buffer.read()), strict=False)
    if reader.is_encrypted:
        return EXIT_ENCRYPTED
    collected: list[str] = []
    total = 0
    for page in reader.pages[:CAPTURE_PDF_MAX_PAGES]:
        text = page.extract_text() or ""
        collected.append(text)
        total += len(text)
        if total >= CAPTURE_TEXT_MAX_CHARS:
            break  # enough to draft tasks from; do not parse the rest
    out = "\n".join(collected)[:CAPTURE_TEXT_MAX_CHARS]
    sys.stdout.buffer.write(out.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(_child_main())
