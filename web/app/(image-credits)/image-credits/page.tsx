import Credits from "@/features/listing-editor/credits";
import { getLocale } from "@/shell/locale";
export default async function Page() {
  return <Credits locale={await getLocale()} />;
}
