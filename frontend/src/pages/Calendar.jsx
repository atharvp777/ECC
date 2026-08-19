import { CalendarDays } from "lucide-react";
import { OrbitEmptyState } from "../components/ui";

export default function Calendar() {
  return (
    <div className="page">
      <OrbitEmptyState
        icon={CalendarDays}
        title="Calendar"
        description="The Calendar workspace is next. It will bring tasks and Google Calendar events together in one view."
      />
    </div>
  );
}
