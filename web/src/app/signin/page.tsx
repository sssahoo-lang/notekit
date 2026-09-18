import { AuthForm } from "@/components/auth-form";

export const metadata = { title: "Sign in · NoteKit" };

export default function Page() {
  return <AuthForm mode="signin" />;
}
