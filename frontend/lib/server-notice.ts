// Pure helpers for the /health response (no imports, so they are unit-testable).

export interface SchemaState {
  revision: string | null;
  expected: string | null;
  /** null when either revision is unknown. */
  up_to_date: boolean | null;
}

export interface Health {
  status: "ok" | "degraded";
  service: string;
  database: "ok" | "unavailable" | "migration_required";
  schema?: SchemaState;
}

/** A sentence for the sign-in page when the server cannot serve accounts yet, else null. */
export function serverNotice(h: Health | null): string | null {
  if (!h) return null;
  if (h.database === "migration_required") {
    const from = h.schema?.revision ?? "unknown";
    const to = h.schema?.expected ?? "the latest version";
    return (
      `This server's database needs an update before anyone can sign in or register ` +
      `(database schema ${from}, server expects ${to}). An administrator should back up ` +
      `the database and run "alembic upgrade head" in the backend folder.`
    );
  }
  if (h.database === "unavailable") return "The EvidenceX server cannot reach its database right now.";
  return null;
}
