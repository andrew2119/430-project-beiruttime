import { getLocale } from '@/shell/locale';
import { MessagesView } from '@/features/messages/view';
export async function generateMetadata() {
  return {title:(await getLocale())==='ar'?'الرسائل الخاصة':'Private messages'};
}
export default MessagesView;
