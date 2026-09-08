import DraftsHome from "@/components/DraftsHome";
import { RequireAuth } from "@/lib/auth";

export default function Page() {
  return (
    <RequireAuth>
      <DraftsHome />
    </RequireAuth>
  );
}
