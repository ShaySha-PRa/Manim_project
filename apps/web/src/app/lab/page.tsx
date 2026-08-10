import { notFound } from "next/navigation";

import { LabPlaceholder } from "../../components/feature-foundation/feature-placeholder";
import { isFeatureFlagEnabled } from "../../lib/feature-flags";

export default function LabPage() {
  if (!isFeatureFlagEnabled(process.env.NEXT_PUBLIC_EXPERIMENT_LAB_ENABLED)) {
    notFound();
  }

  return <LabPlaceholder />;
}
