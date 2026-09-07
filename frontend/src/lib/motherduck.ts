import { Pool, type PoolClient } from "pg";
import { attachDatabasePool } from "@vercel/functions";

// Connects to MotherDuck over its Postgres wire-protocol endpoint, not a
// DuckDB client library — this is MotherDuck's own recommended approach
// for serverless functions (Vercel included): no native DuckDB binary to
// bundle, and the `pg` pool behaves like any other serverless Postgres
// connection. Read-only: this app never writes.
const token = process.env.MOTHERDUCK_TOKEN;
const host = process.env.MOTHERDUCK_HOST ?? "pg.us-east-1-aws.motherduck.com";
const database = process.env.MOTHERDUCK_DB ?? "climate_health_observatory";

if (!token) {
  throw new Error("MOTHERDUCK_TOKEN environment variable is required");
}

const pool = new Pool({
  connectionString: `postgresql://user:${token}@${host}:5432/${database}`,
  ssl: { rejectUnauthorized: true },
  max: 10,
  idleTimeoutMillis: 5000,
});

// Ensures idle connections are cleaned up before a Vercel function
// instance is suspended, preventing connection leaks across invocations.
attachDatabasePool(pool);

export async function withClient<T>(fn: (client: PoolClient) => Promise<T>): Promise<T> {
  const client = await pool.connect();
  try {
    return await fn(client);
  } finally {
    client.release();
  }
}
