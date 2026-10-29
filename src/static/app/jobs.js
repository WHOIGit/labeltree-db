// WoRMS jobs: start, poll, and the progress bars (spec: webapp "WoRMS job
// progress"). A job's status comes from GET /worms/jobs/{job}.

import { api, problem, retrying, sleep } from './api.js';

// Waits before each retry of a job started through the API (worms.client.JOB_BACKOFF).
export const JOB_BACKOFF = [1, 2, 5, 12];
const TOTAL = JOB_BACKOFF.reduce((a, b) => a + b, 0);

export async function startJob(body) {
  const r = await api('POST', '/worms/jobs', body);
  if (r.status !== 202) throw new Error(problem(r));
  return r.data;
}

/**
 * Call `call()` every `interval` ms while `active()`, until `done(data)`;
 * `onUpdate(data)` (which may be async) sees each answer. Each call is
 * retried through transient failures; one that still fails throws. Returns
 * the last data, or null once no longer active.
 */
export async function poll(call, { onUpdate = () => {}, done = () => false, active = () => true, interval = 1000 }) {
  while (active()) {
    const r = await retrying(call);
    if (!r.ok) throw new Error(problem(r));
    await onUpdate(r.data);
    if (done(r.data)) return r.data;
    await sleep(interval);
  }
  return null;
}

/** Poll a job about every second until it ends; `onUpdate(status)` sees each. */
export function pollJob(id, onUpdate, interval = 1000) {
  return poll(() => api('GET', `/worms/jobs/${id}`), { onUpdate, done: s => s.state !== 'running', interval });
}

/** One bar per AphiaID being retried: how far through all its retry waits it is. */
export function retryBars(status, now = Date.now()) {
  return (status?.retrying || []).map(r => {
    const left = Math.max(0, (Date.parse(r.wait_until) - now) / 1000);
    const before = JOB_BACKOFF.slice(0, r.attempt - 1).reduce((a, b) => a + b, 0);
    const current = JOB_BACKOFF[r.attempt - 1] ?? left;
    const done = Math.min(TOTAL, before + Math.max(0, current - left));
    return { aphia_id: r.aphia_id, attempt: r.attempt, retries: r.retries, percent: Math.round((100 * done) / TOTAL) };
  });
}

/** The pause bar while WoRMS rate limiting holds the job, or null. `seen`
 * remembers when the pause was first seen, for its length. */
export function pauseBar(status, seen, now = Date.now()) {
  const paused = status?.paused;
  if (!paused) return null;
  const until = Date.parse(paused.until);
  const key = paused.until;
  if (!seen[key]) seen[key] = now;
  const length = Math.max(1, until - seen[key]);
  const percent = Math.round((100 * Math.min(length, now - seen[key])) / length);
  return { percent, seconds: Math.max(0, Math.ceil((until - now) / 1000)) };
}

export function jobPercent(status) {
  if (!status || !status.total) return status?.state === 'running' ? 0 : 100;
  return Math.round((100 * (status.done + status.failed.length)) / status.total);
}

/**
 * The fetch step shared by the draft editor and the setup wizard: run `fetch`
 * jobs for AphiaIDs whose WoRMS records aren't cached, with the job, retry and
 * pause bars, until they are cached or the user proceeds without them.
 * Components spread it into themselves (no getters: spreading would freeze
 * them) and tick `now` while `job` is set, for the bars.
 */
export function fetchStep() {
  return {
    job: null, jobFailed: null, jobResolve: null, pauseSeen: {}, now: Date.now(),

    /** Fetch `ids` for organization `org`. Returns the AphiaIDs still not
     * fetched when the user proceeds without them ([] if all were). A job
     * that can't be started or followed throws. */
    async fetchMissing(org, ids) {
      try {
        for (;;) {
          const job = await startJob({ kind: 'fetch', org, aphia_ids: ids });
          this.job = job;
          const done = await pollJob(job.id, s => { this.job = s; });
          if (!done.failed.length) return [];
          this.jobFailed = done.failed;
          const choice = await new Promise(resolve => { this.jobResolve = resolve; });
          this.jobFailed = null;
          ids = done.failed.map(x => x.aphia_id);
          if (choice !== 'retry') return ids;
        }
      } finally {
        this.job = null;
      }
    },
    tryAgain() { this.jobResolve?.('retry'); },
    proceedAnyway() { this.jobResolve?.('proceed'); },
    jobBar(j) { return `width:${jobPercent(j)}%`; },
    jobText(j) { return `${j.kind} · ${j.done} of ${j.total} AphiaIDs` + (j.failed.length ? ` · ${j.failed.length} failed` : ''); },
    retries(j) { this.now; return retryBars(j, this.now); },
    pause(j) { this.now; return pauseBar(j, this.pauseSeen, this.now); },
    width(p) { return `width:${p}%`; },
  };
}
