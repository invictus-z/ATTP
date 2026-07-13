import { spawn, type ChildProcess } from "node:child_process";

export interface SuperviseOptions {
  pythonPath: string;
  /** Full argv after the interpreter, e.g. ["-m", "attp.channels.openclaw", "--config", ...]. */
  args: string[];
  env?: NodeJS.ProcessEnv;
  log?: (line: string) => void;
  abortSignal: AbortSignal;
  onFailed?: () => void;
}

/** Backoff schedule between restart attempts (ms). */
const BACKOFF_MS = [1000, 2000, 5000];
const MAX_ATTEMPTS = 5;
const SHUTDOWN_GRACE_MS = 5000;

/**
 * Spawn + supervise the ATTP Python adapter. Restarts with exponential backoff on
 * unexpected exit. Resolves when the abort signal fires (graceful stop) or after
 * MAX_ATTEMPTS crashes (calls onFailed).
 */
export async function supervisePython(opts: SuperviseOptions): Promise<void> {
  const log = opts.log ?? (() => {});

  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    if (opts.abortSignal.aborted) return;

    const child: ChildProcess = spawn(opts.pythonPath, opts.args, {
      env: { ...process.env, ...opts.env },
      stdio: ["ignore", "pipe", "pipe"],
    });
    child.stdout?.on("data", (d: Buffer) => log(strip(d)));
    child.stderr?.on("data", (d: Buffer) => log(strip(d)));

    const exited = new Promise<number | null>((resolve) =>
      child.once("exit", (code) => resolve(code)),
    );
    const aborted = new Promise<void>((resolve) => {
      opts.abortSignal.addEventListener("abort", () => {
        if (!child.killed) {
          child.kill("SIGTERM");
          setTimeout(() => {
            if (!child.killed) child.kill("SIGKILL");
          }, SHUTDOWN_GRACE_MS);
        }
        resolve();
      });
    });

    const code = await Promise.race([exited, aborted]);
    if (opts.abortSignal.aborted) return;

    log(`[attp] python exited code=${code}; attempt ${attempt + 1}/${MAX_ATTEMPTS}`);
    await sleep(BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)]);
  }

  opts.onFailed?.();
}

function strip(d: Buffer): string {
  return d.toString("utf8").replace(/\r?\n$/, "");
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
