/* Types for the fault layer shipped with ROTAX_915IS_FAULT_INTEGRATION.
 *
 * The layer is used AS SHIPPED. Rewriting it in TypeScript would fork a file
 * that has a published contract (digital_twin_visualization_api.md) and a
 * 33/33 browser contract test behind it, and the fork would then be ours to
 * keep correct. Declaring it keeps the boundary explicit instead of leaving an
 * implicit `any` nobody noticed.
 *
 * Sits beside faultLayer.js so TypeScript picks it up for that import.
 */
export class DigitalTwinFaultLayer extends EventTarget {
    constructor(opts: {
      root: unknown; camera?: unknown; controls?: unknown;
      faultRegistry: unknown; componentRegistry: unknown; matrix: unknown;
      options?: Record<string, unknown>;
    });
    setFault(fault: {
      faultId: string; cylinder?: number | null; channel?: string | null;
      magnitude?: number | null; alertLevel?: string; valueState?: string;
      ruleId?: string | null; timestamp?: number;
    }): unknown;
    clearFault(faultId: string,
               opts?: { cylinder?: number | null; channel?: string | null; recover?: boolean }): unknown[];
    clearAll(): void;
    setComponentState(componentId: string, state: string, opts?: Record<string, unknown>): void;
    setTelemetryState(channel: string, state: string, opts?: Record<string, unknown>): void;
    selectAt(ndcX: number, ndcY: number, raycaster?: unknown): string | null;
    focusComponent(componentId: string, opts?: Record<string, unknown>): void;
    focusFault(faultId: string, opts?: Record<string, unknown>): void;
    clearFocus(): void;
    update(dtSeconds: number): void;
    dispose(): void;
  }
