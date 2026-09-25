"""Running a check command and capturing its verdict."""
import subprocess


def run_check(cmd, cwd=".", timeout=600):
    """Run one check command through the shell.

    Returns (exit_code, output). exit_code is None when the check timed out --
    that is deliberately distinct from a non-zero failure, because "did not
    finish" and "said no" are different facts.
    """
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return None, "TIMEOUT after %ss" % timeout
    except OSError as e:
        return 127, "could not start check: %s" % e
