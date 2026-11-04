import { notFound } from "next/navigation";
import Editor from "@/features/listing-editor/editor";
import { SellerLayout } from "@/shell/layouts";
export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();
  return (
    <SellerLayout>
      <Editor id={id} />
    </SellerLayout>
  );
}
