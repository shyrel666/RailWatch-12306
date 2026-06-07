export type CommandRunner = <T>(
  command: string,
  payload?: Record<string, unknown>,
  successText?: string,
) => Promise<T | undefined>;

export type ConfirmDialog = (title: string, content: string) => Promise<boolean>;
