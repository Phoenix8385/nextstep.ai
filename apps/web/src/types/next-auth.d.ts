import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session extends DefaultSession {
    /** Bearer token for the FastAPI backend. */
    accessToken?: string;
    /** Epoch milliseconds when `accessToken` expires. */
    accessTokenExpires?: number;
    user: DefaultSession["user"] & { id: string };
  }

  interface User {
    id: string;
    accessToken: string;
    accessTokenExpires: number;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    accessTokenExpires?: number;
  }
}
