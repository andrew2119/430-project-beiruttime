import VerificationDesk from "@/features/business/verification";
import BusinessBoundary from "@/features/business/boundary";
export default function Page() {
  return (
    <BusinessBoundary>
      <VerificationDesk />
    </BusinessBoundary>
  );
}
