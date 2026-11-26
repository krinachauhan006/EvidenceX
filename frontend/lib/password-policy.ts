// Mirrors backend/app/modules/auth/security.py (password_problem). The server is the
// authority; this only gives earlier, identical feedback in the form.

export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 256;

/** Length in Unicode code points, the same unit Python's len() uses. An emoji such
 *  as "🔒" counts once here, although it is two UTF-16 units in String.length. */
export function passwordLength(password: string): number {
  return Array.from(password).length;
}

/** The first problem with a new password, or null when the server will accept it. */
export function passwordProblem(password: string): string | null {
  const n = passwordLength(password);
  if (n < PASSWORD_MIN) return `The password must have at least ${PASSWORD_MIN} characters.`;
  if (n > PASSWORD_MAX) return `The password must have at most ${PASSWORD_MAX} characters.`;
  if (password.trim() !== password || !password.trim()) {
    return "The password must not start or end with spaces.";
  }
  return null;
}
