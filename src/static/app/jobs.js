// WoRMS jobs: start, poll, and the progress bars (spec: webapp "WoRMS job
// progress"). A job's status comes from GET /worms/jobs/{job}.

import { api, problem } from './api.js';

// Waits before each retry of a job started through the API (worms.client.JOB_BACKOFF).
export const JOB_BACKOFF = [1, 2, 5, 12];
const TOTAL = JOB_BACKOFF.reduce((a, b) => a + b, 0);

export async function startJob(body) {
  const r = await api('POST', '/worms/jobs', body);
  if (r.status !== 202) throw new Error(problem(r));
  return r.data;
}

/** Poll a job about every second until it ends; `onUpdate(status)` sees each. */
export async function pollJob(id, onUpdate, interval = 1000) {
  for (;;) {
    const r = await api('GET', `/worms/jobs/${id}`);
    if (!r.ok) throw new Error(problem(r));
    onUpdate(r.data);
    if (r.data.state !== 'running') return r.data;
    await new Promise(resolve => setTimeout(resolve, interval));
  }
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
