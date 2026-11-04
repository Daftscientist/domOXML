declare module "*takumi-bridge.mjs" {
  export function takumiBridge(requestJson: string): Promise<string>;
  export function installTakumiBridge(
    target?: unknown,
  ): (requestJson: string) => Promise<string>;
}
