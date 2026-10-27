import table from "../../railwatch_policies/notification_channels.json";

// The channel table is shared with railwatch_notify.py. Channels and fields are keyed
// objects and flags appear only when true, so the types below come from the JSON itself.
type Channels = typeof table.channels;
export type NotificationChannelId = keyof Channels;
type FieldsOf<C extends NotificationChannelId> = Channels[C]["fields"];
export type NotificationChannelField = { [C in NotificationChannelId]: keyof FieldsOf<C> & string }[NotificationChannelId];
type FieldSpecOf<F extends NotificationChannelField> =
  { [C in NotificationChannelId]: F extends keyof FieldsOf<C> ? FieldsOf<C>[F] : never }[NotificationChannelId];
export type NotificationSecretField =
  { [F in NotificationChannelField]: FieldSpecOf<F> extends { secret: boolean } ? F : never }[NotificationChannelField];
/** Values a channel's fields hold in the settings: ports and switches state a typed default. */
export type NotificationChannelValues = {
  [F in NotificationChannelField]: FieldSpecOf<F> extends { default: number } ? number
    : FieldSpecOf<F> extends { default: boolean } ? boolean : string
};
type FieldsHolding<T> = { [F in NotificationChannelField]: NotificationChannelValues[F] extends T ? F : never }[NotificationChannelField];
export type NotificationSwitchField = FieldsHolding<boolean>;
export type NotificationTextField = Exclude<FieldsHolding<string>, NotificationSecretField>;

type FieldSpec = { label: string; secret?: boolean; required?: boolean; type?: string; default?: string | number | boolean; allow_newline?: boolean };
const channelSpecs: Record<NotificationChannelId, { label: string; fields: Record<string, FieldSpec> }> = table.channels;
const fieldSpecs = Object.assign({}, ...Object.values(channelSpecs).map((spec) => spec.fields)) as Record<NotificationChannelField, FieldSpec>;

export const NOTIFICATION_CHANNELS = (Object.keys(channelSpecs) as NotificationChannelId[])
  .map((id) => ({ id, label: channelSpecs[id].label }));
export const NOTIFICATION_SECRET_FIELDS = (Object.keys(fieldSpecs) as NotificationChannelField[])
  .filter((name) => fieldSpecs[name].secret) as NotificationSecretField[];

export const NOTIFICATION_REQUIRED_FIELDS = Object.fromEntries((Object.keys(channelSpecs) as NotificationChannelId[])
  .map((id) => [id, Object.keys(channelSpecs[id].fields).filter((name) => channelSpecs[id].fields[name].required)])) as
  Record<NotificationChannelId, NotificationChannelField[]>;

export const isNotificationSecretField = (name: string): name is NotificationSecretField =>
  (NOTIFICATION_SECRET_FIELDS as string[]).includes(name);
export const notificationChannelLabel = (id: NotificationChannelId) => channelSpecs[id].label;
export const notificationFieldLabel = (name: NotificationChannelField) => fieldSpecs[name].label;
