import Memberships from "@/features/business/membership";
import BusinessBoundary from "@/features/business/boundary";
export default function Page() {
  return (
    <BusinessBoundary>
      <Memberships />
    </BusinessBoundary>
  );
}
