import { AuthForm } from "@/components/auth-form";

export const metadata = { title: "Create an account · NoteKit" };

export default function Page() {
  return <AuthForm mode="register" />;
}
