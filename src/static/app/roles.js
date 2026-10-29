// Role checks for enabling controls. The API checks every action again.

export const LADDER = ['reader', 'drafter', 'approver', 'owner'];

/** The user's role in an organization: owner for site admins, null for others. */
export function roleIn(user, org) {
  if (!user?.username) return null;
  if (user.superuser) return 'owner';
  return user.roles?.[org] ?? null;
}

export function atLeast(role, minimum) {
  return role != null && LADDER.indexOf(role) >= LADDER.indexOf(minimum);
}

/** Tooltip for a control the user can't use, or '' if they can. */
export function needs(user, org, minimum) {
  if (!user?.username) return 'Log in to edit';
  return atLeast(roleIn(user, org), minimum) ? '' : `Needs the ${minimum} role`;
}
