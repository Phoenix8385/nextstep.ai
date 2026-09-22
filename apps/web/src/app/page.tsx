import { redirect } from "next/navigation";

/** The dashboard is the home page. */
export default function HomePage() {
  redirect("/jobs");
}
