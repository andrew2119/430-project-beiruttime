import ListingsView from "@/features/listing-editor/list-view";
import { SellerLayout } from "@/shell/layouts";
export default function Page() {
  return (
    <SellerLayout>
      <ListingsView />
    </SellerLayout>
  );
}
