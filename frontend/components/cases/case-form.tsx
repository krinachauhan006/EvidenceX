"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createCase, updateCase } from "@/lib/api/cases";
import { ApiError } from "@/lib/api/client";
import type { Case } from "@/lib/types/case";

interface Props {
  // When provided, the form edits an existing case; otherwise it creates one.
  existing?: Case;
  onDone?: () => void;
}

export function CaseForm({ existing, onDone }: Props) {
  const router = useRouter();
  const [title, setTitle] = useState(existing?.title ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const titleInvalid = title.trim().length === 0;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    // Client-side validation mirrors the server rule (non-empty title).
    if (titleInvalid) {
      setError("Title is required.");
      return;
    }
    setSubmitting(true);
    try {
      if (existing) {
        await updateCase(existing.id, {
          title: title.trim(),
          description: description.trim() || null,
        });
      } else {
        await createCase({
          title: title.trim(),
          description: description.trim() || null,
        });
      }
      onDone?.();
      router.refresh();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? `Could not save case (${err.status}).`
          : "Could not save case.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label htmlFor="title" className="mb-1 block text-sm text-slate-300">
          Title <span className="text-inconsistency">*</span>
        </label>
        <input
          id="title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
          required
          aria-invalid={titleInvalid}
          className="w-full rounded-md border border-navy-700 bg-navy-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500"
          placeholder="e.g. Operation Nightfall"
        />
      </div>
      <div>
        <label htmlFor="description" className="mb-1 block text-sm text-slate-300">
          Description
        </label>
        <textarea
          id="description"
          value={description ?? ""}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          className="w-full rounded-md border border-navy-700 bg-navy-900 px-3 py-2 text-sm text-slate-100 placeholder-slate-500"
          placeholder="Optional notes about this case"
        />
      </div>

      {error && (
        <p role="alert" className="text-sm text-inconsistency">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting || titleInvalid}
          className="rounded-md bg-navy-700 px-4 py-2 text-sm font-medium text-slate-100 hover:bg-navy-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "Saving…" : existing ? "Save changes" : "Create case"}
        </button>
      </div>
    </form>
  );
}
