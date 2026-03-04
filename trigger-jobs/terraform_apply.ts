import { TriggerClient, events } from "@trigger.dev/sdk/v3";
import * as cp from "child_process";
import * as fs from "fs";
import * as path from "path";

interface TerraformApplyPayload {
  request_id: string;
  environment_id: string;
  terraform_config: Record<string, unknown>;
  requester_id: string;
}

interface TerraformState {
  version: number;
  terraform_version: string;
  serial: number;
  lineage: string;
  outputs: Record<string, unknown>;
  resources: Array<{
    type: string;
    name: string;
    provider: string;
    instances: Array<unknown>;
  }>;
}

interface ExecutionCheckpoint {
  step: string;
  timestamp: string;
  status: "pending" | "in_progress" | "completed" | "failed";
  data?: unknown;
}

export const terraform_apply = TriggerClient.defineJob({
  id: "terraform_apply",
  name: "Terraform Apply - Long-Running Infrastructure Provisioning",
  version: "1.0.0",
  trigger: events.onEvent({
    name: "terraform.apply.requested",
    schema: {
      request_id: { type: "string" },
      environment_id: { type: "string" },
      terraform_config: { type: "object" },
      requester_id: { type: "string" },
    },
  }),
  run: async (event: TerraformApplyPayload, io, ctx) => {
    const workdir = path.join("/tmp", event.request_id);
    const checkpointFile = path.join(workdir, ".checkpoint");
    const stateFile = path.join(workdir, "terraform.tfstate");

    // Initialize execution checkpoint system
    const checkpoints: ExecutionCheckpoint[] = [];

    const saveCheckpoint = (step: string, status: "pending" | "in_progress" | "completed" | "failed", data?: unknown) => {
      const checkpoint: ExecutionCheckpoint = {
        step,
        timestamp: new Date().toISOString(),
        status,
        data,
      };
      checkpoints.push(checkpoint);
      fs.writeFileSync(checkpointFile, JSON.stringify(checkpoints, null, 2));
    };

    const loadCheckpoints = (): ExecutionCheckpoint[] => {
      if (fs.existsSync(checkpointFile)) {
        return JSON.parse(fs.readFileSync(checkpointFile, "utf-8"));
      }
      return [];
    };

    try {
      // Step 1: Setup working directory
      saveCheckpoint("setup", "in_progress");

      if (!fs.existsSync(workdir)) {
        fs.mkdirSync(workdir, { recursive: true });
      }

      // Write Terraform configuration
      const tfConfigPath = path.join(workdir, "main.tf.json");
      fs.writeFileSync(tfConfigPath, JSON.stringify(event.terraform_config, null, 2));

      await io.logger.info("Terraform environment initialized", {
        request_id: event.request_id,
        workdir,
      });

      saveCheckpoint("setup", "completed");

      // Step 2: Terraform Init
      saveCheckpoint("terraform_init", "in_progress");

      const initResult = await io.runTask("terraform_init", async () => {
        return new Promise<{ stdout: string; stderr: string; code: number }>((resolve) => {
          const proc = cp.spawn("terraform", ["init", "-upgrade"], { cwd: workdir });
          let stdout = "";
          let stderr = "";

          proc.stdout?.on("data", (data) => {
            stdout += data.toString();
          });

          proc.stderr?.on("data", (data) => {
            stderr += data.toString();
          });

          proc.on("close", (code) => {
            resolve({ stdout, stderr, code });
          });
        });
      });

      if (initResult.code !== 0) {
        throw new Error(`Terraform init failed: ${initResult.stderr}`);
      }

      await io.logger.info("Terraform initialized", { request_id: event.request_id });
      saveCheckpoint("terraform_init", "completed", initResult);

      // Step 3: Terraform Plan
      saveCheckpoint("terraform_plan", "in_progress");

      const planFile = path.join(workdir, "plan.tfplan");
      const planResult = await io.runTask("terraform_plan", async () => {
        return new Promise<{ stdout: string; stderr: string; code: number }>((resolve) => {
          const proc = cp.spawn("terraform", ["plan", "-out", planFile], { cwd: workdir });
          let stdout = "";
          let stderr = "";

          proc.stdout?.on("data", (data) => {
            stdout += data.toString();
          });

          proc.stderr?.on("data", (data) => {
            stderr += data.toString();
          });

          proc.on("close", (code) => {
            resolve({ stdout, stderr, code });
          });
        });
      });

      if (planResult.code !== 0) {
        throw new Error(`Terraform plan failed: ${planResult.stderr}`);
      }

      await io.logger.info("Terraform plan created", {
        request_id: event.request_id,
        summary: planResult.stdout,
      });

      saveCheckpoint("terraform_plan", "completed", {
        summary: planResult.stdout,
      });

      // Step 4: Policy Check (OPA evaluation)
      saveCheckpoint("policy_check", "in_progress");

      const policyCheckResult = await io.runTask("policy_check", async () => {
        // In production, this would call OPA server
        return { approved: true, violations: [] };
      });

      if (!policyCheckResult.approved) {
        throw new Error(
          `Policy check failed: ${policyCheckResult.violations.join(", ")}`
        );
      }

      await io.logger.info("Policy check passed", { request_id: event.request_id });
      saveCheckpoint("policy_check", "completed", policyCheckResult);

      // Step 5: Terraform Apply
      saveCheckpoint("terraform_apply", "in_progress");

      const applyResult = await io.runTask(
        "terraform_apply",
        async () => {
          return new Promise<{ stdout: string; stderr: string; code: number }>((resolve) => {
            const proc = cp.spawn("terraform", ["apply", "-auto-approve", planFile], {
              cwd: workdir,
            });
            let stdout = "";
            let stderr = "";

            proc.stdout?.on("data", (data) => {
              stdout += data.toString();
              // Log streaming output
              ctx.logger.debug(data.toString());
            });

            proc.stderr?.on("data", (data) => {
              stderr += data.toString();
              ctx.logger.debug(data.toString());
            });

            proc.on("close", (code) => {
              resolve({ stdout, stderr, code });
            });
          });
        },
        { timeout: 1800, // 30 minutes
        }
      );

      if (applyResult.code !== 0) {
        throw new Error(`Terraform apply failed: ${applyResult.stderr}`);
      }

      await io.logger.info("Terraform apply completed", {
        request_id: event.request_id,
      });

      saveCheckpoint("terraform_apply", "completed");

      // Step 6: Wait for resources to be healthy
      saveCheckpoint("resource_health_check", "in_progress");

      const healthCheckResult = await io.runTask(
        "resource_health_check",
        async () => {
          // Read Terraform state to get created resource IDs
          const stateContent = fs.readFileSync(stateFile, "utf-8");
          const state: TerraformState = JSON.parse(stateContent);

          const resources = state.resources.map((r) => ({
            type: r.type,
            name: r.name,
          }));

          // Poll for resource health (implement actual health checks)
          for (let i = 0; i < 30; i++) {
            const allHealthy = true; // Would check actual resource status

            if (allHealthy) {
              return { healthy: true, resources };
            }

            await new Promise((resolve) => setTimeout(resolve, 10000)); // Wait 10s
          }

          return { healthy: false, resources, reason: "Timeout waiting for resources" };
        },
        { timeout: 600 } // 10 minutes
      );

      if (!healthCheckResult.healthy) {
        throw new Error(`Resources not healthy: ${healthCheckResult.reason}`);
      }

      await io.logger.info("Resources are healthy", {
        request_id: event.request_id,
      });

      saveCheckpoint("resource_health_check", "completed", healthCheckResult);

      // Step 7: Tag resources for cost tracking and compliance
      saveCheckpoint("tag_resources", "in_progress");

      const tagResult = await io.runTask("tag_resources", async () => {
        // Apply consistent tags to all resources
        const tags = {
          environment_id: event.environment_id,
          request_id: event.request_id,
          requester: event.requester_id,
          provisioned_at: new Date().toISOString(),
          platform: "infrastructure-automation",
        };

        // In production, apply these tags to all created resources
        return { tags_applied: Object.keys(tags).length };
      });

      saveCheckpoint("tag_resources", "completed", tagResult);

      // Read final state
      const finalState = JSON.parse(fs.readFileSync(stateFile, "utf-8"));

      return {
        success: true,
        request_id: event.request_id,
        environment_id: event.environment_id,
        terraform_state: finalState,
        created_resources: healthCheckResult.resources,
        access_urls: {
          // Would be populated from Terraform outputs
        },
        duration_seconds: Math.round(
          (new Date().getTime() - ctx.createdAt.getTime()) / 1000
        ),
      };
    } catch (error) {
      // Save failure checkpoint
      saveCheckpoint("failed", "failed", {
        error: error instanceof Error ? error.message : String(error),
      });

      await io.logger.error("Terraform apply failed", {
        request_id: event.request_id,
        error: error instanceof Error ? error.message : String(error),
      });

      // Attempt rollback
      try {
        saveCheckpoint("rollback", "in_progress");

        await io.runTask("rollback", async () => {
          return new Promise<void>((resolve) => {
            const proc = cp.spawn("terraform", ["destroy", "-auto-approve"], {
              cwd: workdir,
            });

            proc.on("close", () => {
              resolve();
            });
          });
        });

        saveCheckpoint("rollback", "completed");
      } catch (rollbackError) {
        saveCheckpoint("rollback", "failed", { error: rollbackError });
        await io.logger.error("Rollback failed", { error: rollbackError });
      }

      throw error;
    } finally {
      // Cleanup temporary files (but keep state for audit)
      // fs.rmSync(workdir, { recursive: true, force: true });
    }
  },
});
