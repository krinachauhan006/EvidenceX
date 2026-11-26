"use client";

import { useId, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

/**
 * Password input with a show/hide toggle. The toggle is a real button
 * (type="button", so it never submits the form) and only switches the input's
 * type: the value, caret and autocomplete hints are untouched, so typing can
 * continue and password managers keep working. Pressing the toggle with a mouse
 * does not move focus out of the input.
 */
export function PasswordField({
  label,
  value,
  onChange,
  autoComplete,
  describedBy,
  invalid,
  hint,
  inputClassName,
  revealed: revealedProp,
  onRevealedChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete: "current-password" | "new-password";
  describedBy?: string;
  invalid?: boolean;
  hint?: React.ReactNode;
  inputClassName: string;
  revealed?: boolean;
  onRevealedChange?: (revealed: boolean) => void;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const [own, setOwn] = useState(false);
  const revealed = revealedProp ?? own;
  const setRevealed = (v: boolean) => (onRevealedChange ? onRevealedChange(v) : setOwn(v));
  const described = [hint ? hintId : null, describedBy].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-slate-300">
        {label}
      </label>
      <div className="relative mt-1">
        <input
          id={id}
          name="password"
          type={revealed ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          required
          maxLength={512}
          autoComplete={autoComplete}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-invalid={invalid || undefined}
          aria-describedby={described}
          className={`${inputClassName} pr-11`}
          data-testid="password-input"
        />
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => setRevealed(!revealed)}
          aria-label={revealed ? "Hide password" : "Show password"}
          aria-pressed={revealed}
          aria-controls={id}
          title={revealed ? "Hide password" : "Show password"}
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md text-slate-400 transition-colors hover:text-slate-100 focus-visible:text-slate-100 focus-visible:ring-offset-0"
          data-testid="password-toggle"
        >
          {revealed ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
        </button>
      </div>
      {hint && (
        <p id={hintId} className="mt-1 text-xs text-slate-400">
          {hint}
        </p>
      )}
    </div>
  );
}
