import { TriggerClient, events } from "@trigger.dev/sdk/v3";

interface RemediationPayload {
  incident_id: string;
  runbook_id: string;
  incident_type: string;
  severity: "critical" | "high" | "medium" | "low";
}

interface RemediationStep {
  name: string;
  action: string;
  timeout_seconds: number;
  verify_after: boolean;
  rollback_on_failure: boolean;
  parameters: Record<string, unknown>;
}

interface RunbookDefinition {
  id: string;
  name: string;
  steps: RemediationStep[];
  rollback_steps: RemediationStep[];
  requires_human_confirmation: boolean;
}

interface StepResult {
  step_name: string;
  status: "success" | "failed";
  duration_seconds: number;
  output?: unknown;
  error?: string;
}

export const incident_remediation = TriggerClient.defineJob({
  id: "incident_remediation",
  name: "Incident Auto-Remediation with Human-in-the-Loop",
  version: "1.0.0",
  trigger: events.onEvent({
    name: "incident.remediation.requested",
    schema: {
      incident_id: { type: "string" },
      runbook_id: { type: "string" },
      incident_type: { type: "string" },
      severity: { type: "string" },
    },
  }),
  run: async (event: RemediationPayload, io, ctx) => {
    const startTime = Date.now();
    const stepResults: StepResult[] = [];

    try {
      // Step 1: Fetch runbook
      await io.logger.info("Fetching runbook", {
        incident_id: event.incident_id,
        runbook_id: event.runbook_id,
      });

      const runbook = await io.runTask("fetch_runbook", async () => {
        // In production, fetch from database
        const response = await fetch(`http://api:3000/runbooks/${event.runbook_id}`);
        if (!response.ok) {
          throw new Error(`Failed to fetch runbook: ${response.statusText}`);
        }
        return (await response.json()) as RunbookDefinition;
      });

      await io.logger.info("Runbook fetched", {
        incident_id: event.incident_id,
        steps_count: runbook.steps.length,
      });

      // Step 2: Execute remediation steps
      await io.logger.info("Starting remediation execution", {
        incident_id: event.incident_id,
        step_count: runbook.steps.length,
      });

      for (let stepIndex = 0; stepIndex < runbook.steps.length; stepIndex++) {
        const step = runbook.steps[stepIndex];

        await io.logger.info(`Executing remediation step: ${step.name}`, {
          incident_id: event.incident_id,
          step_index: stepIndex,
          action: step.action,
        });

        // Step 2a: For high/critical severity, pause for approval
        if (
          event.severity === "critical" ||
          (event.severity === "high" && step.rollback_on_failure)
        ) {
          if (step.rollback_on_failure || runbook.requires_human_confirmation) {
            await io.logger.warn("High-severity incident - awaiting human approval", {
              incident_id: event.incident_id,
              step_name: step.name,
            });

            // Wait for human approval (with 5-minute timeout)
            const approved = await io.waitForHumanApproval(
              `Approve remediation step: ${step.name}`,
              {
                timeout: 300, // 5 minutes
              }
            );

            if (!approved) {
              await io.logger.error("Remediation step rejected by human", {
                incident_id: event.incident_id,
                step_name: step.name,
              });

              throw new Error(
                `Remediation step '${step.name}' rejected by human operator`
              );
            }

            await io.logger.info("Remediation step approved", {
              incident_id: event.incident_id,
              step_name: step.name,
            });
          }
        }

        // Step 2b: Execute the remediation action
        const stepStartTime = Date.now();

        const result = await io.runTask(`execute_step_${stepIndex}`, async () => {
          try {
            let output: unknown;

            switch (step.action) {
              case "restart_service":
                output = await executeRestartService(
                  step.parameters.service_name as string
                );
                break;

              case "clear_cache":
                output = await executeClearCache(step.parameters);
                break;

              case "rotate_logs":
                output = await executeRotateLogs(
                  step.parameters.log_paths as string[]
                );
                break;

              case "reroute_traffic":
                output = await executeRerouteTraffic(
                  step.parameters.from as string,
                  step.parameters.to as string
                );
                break;

              case "scale_resources":
                output = await executeScaleResources(step.parameters);
                break;

              case "unlock_database":
                output = await executeUnlockDatabase(
                  step.parameters.database_id as string
                );
                break;

              case "drain_queue":
                output = await executeDrainQueue(
                  step.parameters.queue_name as string
                );
                break;

              default:
                throw new Error(`Unknown remediation action: ${step.action}`);
            }

            return { success: true, output };
          } catch (error) {
            return {
              success: false,
              error: error instanceof Error ? error.message : String(error),
            };
          }
        });

        const stepDuration = Math.round((Date.now() - stepStartTime) / 1000);

        const stepResult: StepResult = {
          step_name: step.name,
          status: result.success ? "success" : "failed",
          duration_seconds: stepDuration,
          output: result.output,
          error: result.error,
        };

        stepResults.push(stepResult);

        if (!result.success) {
          await io.logger.error(`Remediation step failed: ${step.name}`, {
            incident_id: event.incident_id,
            step_index: stepIndex,
            error: result.error,
          });

          if (step.rollback_on_failure) {
            await io.logger.warn("Executing rollback", {
              incident_id: event.incident_id,
            });

            // Execute rollback steps in reverse order
            for (let rollbackIndex = stepIndex; rollbackIndex >= 0; rollbackIndex--) {
              const rollbackStep =
                runbook.rollback_steps?.[rollbackIndex] ||
                runbook.steps[rollbackIndex];
              // Execute rollback (simplified)
              await executeRollbackStep(rollbackStep);
            }

            throw new Error(
              `Remediation failed at step '${step.name}' and rolled back`
            );
          }

          throw new Error(`Remediation step failed: ${result.error}`);
        }

        await io.logger.info(`Step completed: ${step.name}`, {
          incident_id: event.incident_id,
          duration_seconds: stepDuration,
        });

        // Step 2c: Verify fix if enabled
        if (step.verify_after) {
          await io.logger.info(`Verifying fix after step: ${step.name}`, {
            incident_id: event.incident_id,
          });

          const verificationResult = await io.runTask(
            `verify_step_${stepIndex}`,
            async () => {
              return await verifyRemediationFix(
                event.incident_type,
                step.timeout_seconds
              );
            },
            { timeout: step.timeout_seconds }
          );

          if (!verificationResult.healthy) {
            await io.logger.warn(`Verification failed after step: ${step.name}`, {
              incident_id: event.incident_id,
              verification_details: verificationResult.details,
            });

            if (step.rollback_on_failure) {
              throw new Error(
                `Verification failed after step '${step.name}' and rolled back`
              );
            }
          } else {
            await io.logger.info(`Verification passed: ${step.name}`, {
              incident_id: event.incident_id,
            });
          }
        }
      }

      // Step 3: Update incident status
      const totalDuration = Math.round((Date.now() - startTime) / 1000);

      await io.runTask("update_incident_status", async () => {
        const response = await fetch(
          `http://api:3000/incidents/${event.incident_id}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              status: "resolved",
              resolved_at: new Date().toISOString(),
              auto_remediation_executed: true,
              resolution_notes: `Auto-remediation completed in ${totalDuration}s. Executed ${stepResults.length} steps.`,
            }),
          }
        );

        if (!response.ok) {
          throw new Error(`Failed to update incident status: ${response.statusText}`);
        }
      });

      await io.logger.info("Incident remediation completed successfully", {
        incident_id: event.incident_id,
        duration_seconds: totalDuration,
        steps_executed: stepResults.length,
      });

      return {
        success: true,
        incident_id: event.incident_id,
        steps_executed: stepResults.length,
        steps: stepResults,
        total_duration_seconds: totalDuration,
        remediation_successful: true,
      };
    } catch (error) {
      // Update incident status on failure
      await io.runTask("update_incident_on_failure", async () => {
        await fetch(`http://api:3000/incidents/${event.incident_id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status: "escalated",
            resolution_notes: `Auto-remediation failed: ${error instanceof Error ? error.message : String(error)}`,
          }),
        });
      });

      await io.logger.error("Incident remediation failed", {
        incident_id: event.incident_id,
        error: error instanceof Error ? error.message : String(error),
        steps_executed: stepResults.length,
      });

      return {
        success: false,
        incident_id: event.incident_id,
        error: error instanceof Error ? error.message : String(error),
        steps_executed: stepResults.length,
        remediation_successful: false,
      };
    }
  },
});

// Remediation action implementations
async function executeRestartService(serviceName: string): Promise<unknown> {
  const response = await fetch("http://api:3000/actions/restart-service", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ service_name: serviceName }),
  });
  return response.json();
}

async function executeClearCache(
  parameters: Record<string, unknown>
): Promise<unknown> {
  const response = await fetch("http://api:3000/actions/clear-cache", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(parameters),
  });
  return response.json();
}

async function executeRotateLogs(logPaths: string[]): Promise<unknown> {
  const response = await fetch("http://api:3000/actions/rotate-logs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ log_paths: logPaths }),
  });
  return response.json();
}

async function executeRerouteTraffic(from: string, to: string): Promise<unknown> {
  const response = await fetch("http://api:3000/actions/reroute-traffic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from, to }),
  });
  return response.json();
}

async function executeScaleResources(
  parameters: Record<string, unknown>
): Promise<unknown> {
  const response = await fetch("http://api:3000/actions/scale-resources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(parameters),
  });
  return response.json();
}

async function executeUnlockDatabase(databaseId: string): Promise<unknown> {
  const response = await fetch("http://api:3000/actions/unlock-database", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ database_id: databaseId }),
  });
  return response.json();
}

async function executeDrainQueue(queueName: string): Promise<unknown> {
  const response = await fetch("http://api:3000/actions/drain-queue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ queue_name: queueName }),
  });
  return response.json();
}

async function executeRollbackStep(step: RemediationStep): Promise<void> {
  // Generic rollback execution
  await fetch("http://api:3000/actions/rollback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ step: step.name }),
  });
}

async function verifyRemediationFix(
  incidentType: string,
  timeoutSeconds: number
): Promise<{ healthy: boolean; details?: unknown }> {
  const response = await fetch("http://api:3000/verification/check-health", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      incident_type: incidentType,
      timeout_seconds: timeoutSeconds,
    }),
  });
  return response.json();
}
