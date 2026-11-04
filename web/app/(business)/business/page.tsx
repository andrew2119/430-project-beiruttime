import BusinessDirectory from "@/features/business/directory";
import BusinessBoundary from "@/features/business/boundary";
export default function Page() {
  return (
    <BusinessBoundary>
      <BusinessDirectory />
    </BusinessBoundary>
  );
}
