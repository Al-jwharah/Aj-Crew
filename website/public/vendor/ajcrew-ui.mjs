// Vendor stub: re-exports @ajcrew/ui from the host.
const m = window.__ajcrew_modules?.['@ajcrew/ui']
if (!m) throw new Error('[vendor/ajcrew-ui] Host modules not initialized.')
export const {
  Card, CardTitle, Btn, SendBtn, Input, SearchInput,
  Badge, SourceBadge, StatCard, Skeleton, ContentSkeleton,
  EmptyState, PageHeader, Toggle, InfoTip, SegmentedControl,
  MarkdownRenderer, Clickable, Modal, ErrorNotice,
  SettingsSection, SettingsCard, SettingsInput, SettingsToggle, SettingsSelect,
  Select, guideCaution,
} = m
