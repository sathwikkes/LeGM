import DraftRoom from "@/components/DraftRoom";
import { RequireAuth } from "@/lib/auth";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <RequireAuth>
      <DraftRoom draftId={id} />
    </RequireAuth>
  );
}
