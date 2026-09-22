/**
 * NextAuth configuration.
 *
 * Credentials sign-in delegates to the FastAPI `/auth/login` endpoint and
 * keeps the returned JWT inside NextAuth's own encrypted session cookie. The
 * backend token is exposed to the browser only through `session.accessToken`
 * so `api-client.ts` can attach it as a Bearer header.
 *
 * Security notes:
 * - NEXTAUTH_SECRET must be a long random string in every environment; the
 *   NextAuth cookie is the only place the backend token lives client-side.
 * - Sessions are capped to the backend token's own lifetime, so a revoked or
 *   expired backend token cannot outlive the NextAuth session.
 */

import type { NextAuthOptions } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

import type { TokenResponse } from "@/types/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const authOptions: NextAuthOptions = {
  session: { strategy: "jwt" },
  pages: { signIn: "/login" },
  providers: [
    CredentialsProvider({
      name: "Email and password",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials.password) return null;
        const response = await fetch(`${API_URL}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: credentials.email, password: credentials.password }),
        });
        if (!response.ok) return null;
        const data = (await response.json()) as TokenResponse;
        return {
          id: data.user.id,
          email: data.user.email,
          name: data.user.full_name,
          accessToken: data.access_token,
          accessTokenExpires: Date.now() + data.expires_in * 1000,
        };
      },
    }),
  ],
  callbacks: {
    jwt({ token, user }) {
      if (user) {
        token.sub = user.id;
        token.accessToken = user.accessToken;
        token.accessTokenExpires = user.accessTokenExpires;
      }
      return token;
    },
    session({ session, token }) {
      session.accessToken = token.accessToken;
      session.accessTokenExpires = token.accessTokenExpires;
      session.user = { ...session.user, id: token.sub ?? "" };
      // Align the session's expiry with the backend token so they lapse together.
      if (token.accessTokenExpires) {
        session.expires = new Date(token.accessTokenExpires).toISOString();
      }
      return session;
    },
  },
};
