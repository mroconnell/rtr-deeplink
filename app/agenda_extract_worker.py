"""Extract one PDF's text in a throwaway process, under a memory ceiling.

Started by `app.agenda_text.extract_pdf_isolated`; not meant to be run by
hand:

    python -m app.agenda_extract_worker <path-to-pdf> <memory-limit-mb>

Ported from rtr-upcoming's `app/extract_worker.py` (WO-1966). Why a
separate process: a PDF parse can need far more memory than the file is
big. rtr-upcoming measured Berkeley's 97 MB packet near 1 GB and Oakley's
81 MB packet at 2.3 GB before its page-cache fix. Here the parse runs from
the Archive web service, where going over the instance's memory is not an
exception but a restart of every request in flight. In a child process the
same document can only take the child down; the parent records "too heavy"
and carries on. The child also hands every byte back when it exits.

Prints one JSON object: {"text", "format"}. Exit status 0 is success, 3
means the memory ceiling was hit, anything else is a crash.
"""

import json
import sys

EXIT_MEMORY = 3


def apply_limit(megabytes) -> bool:
    """Cap this process's heap with RLIMIT_DATA (counts the private
    anonymous memory a PDF parse allocates, unlike RLIMIT_AS, which also
    counts every mapped library). Linux only; macOS rejects the call, and
    the ceiling exists to protect the Render instance, not a laptop."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        import resource

        limit = int(megabytes) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_DATA, (limit, limit))
        return True
    except (ImportError, ValueError, OSError):
        return False


def main(argv) -> int:
    path, megabytes = argv[1], argv[2]
    apply_limit(megabytes)
    try:
        # Imported after the limit is set, so the limit covers the whole run.
        from app import agenda_text

        with open(path, "rb") as f:
            data = f.read()
        text, fmt = agenda_text.extract(data, "application/pdf")
    except MemoryError:
        sys.stderr.write("memory ceiling reached\n")
        return EXIT_MEMORY
    sys.stdout.write(json.dumps({"text": text, "format": fmt}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
