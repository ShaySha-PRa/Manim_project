import { notFound } from "next/navigation";

import { StudioPlaceholder } from "../../components/feature-foundation/feature-placeholder";
import { isFeatureFlagEnabled } from "../../lib/feature-flags";

export default function StudioPage() {
  if (!isFeatureFlagEnabled(process.env.NEXT_PUBLIC_STUDIO_ENABLED)) {
    notFound();
  }

  return <StudioPlaceholder />;
}
