import React from "react";
import {
  Body,
  Button,
  Container,
  Head,
  Hr,
  Html,
  Link,
  Preview,
  Row,
  Section,
  Text,
  Column,
} from "@react-email/components";

interface AffectedService {
  name: string;
  status: string;
  impacted_users?: number;
}

interface SuggestedRunbook {
  id: string;
  name: string;
  estimated_time_minutes: number;
  success_rate: number;
}

interface IncidentEscalationProps {
  incidentId: string;
  title: string;
  description: string;
  severity: "critical" | "high" | "medium" | "low";
  incidentType: string;
  affectedServices: AffectedService[];
  classification_confidence: number;
  suggestedRunbook?: SuggestedRunbook;
  incidentUrl: string;
  dashboardUrl: string;
  onCallEngineer: string;
  onCallEmail: string;
  statusPageUrl: string;
}

export const IncidentEscalation: React.FC<IncidentEscalationProps> = ({
  incidentId,
  title,
  description,
  severity,
  incidentType,
  affectedServices,
  classification_confidence,
  suggestedRunbook,
  incidentUrl,
  dashboardUrl,
  onCallEngineer,
  onCallEmail,
  statusPageUrl,
}) => {
  const severityConfig = {
    critical: {
      bg: "#c0392b",
      color: "#fff",
      badge: "🔴 CRITICAL",
      sound: "alert",
    },
    high: {
      bg: "#e67e22",
      color: "#fff",
      badge: "🟠 HIGH",
      sound: "alert",
    },
    medium: {
      bg: "#f39c12",
      color: "#fff",
      badge: "🟡 MEDIUM",
      sound: "none",
    },
    low: {
      bg: "#3498db",
      color: "#fff",
      badge: "🔵 LOW",
      sound: "none",
    },
  };

  const config = severityConfig[severity];
  const totalImpactedUsers = affectedServices.reduce(
    (sum, s) => sum + (s.impacted_users || 0),
    0
  );

  return (
    <Html>
      <Head />
      <Preview>
        INCIDENT: {severity.toUpperCase()} - {title}
      </Preview>
      <Body style={main}>
        <Container style={container}>
          {/* Critical Alert Header */}
          <Section style={{ ...header, backgroundColor: config.bg }}>
            <Text style={badgeText}>{config.badge}</Text>
            <Text style={headerTitleText}>{title}</Text>
            <Text style={headerSubtext}>Incident #{incidentId}</Text>
          </Section>

          {/* Quick Summary */}
          <Section style={summarySection}>
            <Row>
              <Column style={summaryBox}>
                <Text style={summaryLabel}>TYPE</Text>
                <Text style={summaryValue}>{incidentType}</Text>
              </Column>
              <Column style={summaryBox}>
                <Text style={summaryLabel}>CONFIDENCE</Text>
                <Text style={summaryValue}>
                  {(classification_confidence * 100).toFixed(0)}%
                </Text>
              </Column>
              <Column style={summaryBox}>
                <Text style={summaryLabel}>IMPACTED USERS</Text>
                <Text style={summaryValue}>{totalImpactedUsers}</Text>
              </Column>
            </Row>
          </Section>

          {/* Description */}
          <Section style={contentSection}>
            <Text style={sectionTitle}>Description</Text>
            <Text style={descriptionText}>{description}</Text>
          </Section>

          {/* Affected Services */}
          {affectedServices.length > 0 && (
            <Section style={contentSection}>
              <Text style={sectionTitle}>Affected Services</Text>

              {affectedServices.map((service, idx) => (
                <Section key={idx} style={serviceBox}>
                  <Row>
                    <Column style={{ width: "70%" }}>
                      <Text style={serviceName}>{service.name}</Text>
                      {service.impacted_users && (
                        <Text style={serviceSubtext}>
                          Impacted Users: {service.impacted_users}
                        </Text>
                      )}
                    </Column>
                    <Column style={{ width: "30%", textAlign: "right" }}>
                      <Text
                        style={{
                          ...statusBadge,
                          backgroundColor:
                            service.status === "degraded"
                              ? "#f39c12"
                              : "#c0392b",
                        }}
                      >
                        {service.status.toUpperCase()}
                      </Text>
                    </Column>
                  </Row>
                </Section>
              ))}
            </Section>
          )}

          {/* Suggested Runbook */}
          {suggestedRunbook && (
            <Section style={runbookSection}>
              <Text style={sectionTitle}>Suggested Auto-Remediation</Text>

              <Section style={runbookBox}>
                <Text style={runbookName}>{suggestedRunbook.name}</Text>

                <Row style={{ marginTop: "12px" }}>
                  <Column style={{ width: "50%" }}>
                    <Text style={runbookDetail}>
                      Est. Time: {suggestedRunbook.estimated_time_minutes} min
                    </Text>
                  </Column>
                  <Column style={{ width: "50%", textAlign: "right" }}>
                    <Text style={runbookDetail}>
                      Success Rate: {(suggestedRunbook.success_rate * 100).toFixed(0)}%
                    </Text>
                  </Column>
                </Row>

                <Text style={runbookNote}>
                  This runbook has been automatically selected based on incident
                  classification. Review before approval.
                </Text>

                <Button style={buttonApprove} href={incidentUrl}>
                  Review & Approve Remediation
                </Button>
              </Section>
            </Section>
          )}

          {/* On-Call Assignment */}
          <Section style={contentSection}>
            <Text style={sectionTitle}>On-Call Assignment</Text>

            <Section style={oncallBox}>
              <Text style={oncallLabel}>On-Call Engineer</Text>
              <Text style={oncallName}>{onCallEngineer}</Text>
              <Text style={oncallEmail}>
                <Link href={`mailto:${onCallEmail}`}>{onCallEmail}</Link>
              </Text>
              <Button style={buttonPrimary} href={incidentUrl}>
                Open Incident Details
              </Button>
            </Section>
          </Section>

          {/* Critical Actions */}
          <Section style={actionsSection}>
            <Text style={actionsTitle}>REQUIRED ACTIONS</Text>

            <ol style={actionsList}>
              <li>
                <Text style={actionItem}>
                  <strong>Acknowledge</strong> this incident in the platform
                </Text>
              </li>
              <li>
                <Text style={actionItem}>
                  <strong>Assess</strong> the situation and review affected services
                </Text>
              </li>
              <li>
                <Text style={actionItem}>
                  {suggestedRunbook
                    ? "Review the suggested runbook and approve auto-remediation"
                    : "Execute the appropriate remediation playbook"}
                </Text>
              </li>
              <li>
                <Text style={actionItem}>
                  <strong>Monitor</strong> metrics to confirm resolution
                </Text>
              </li>
              <li>
                <Text style={actionItem}>
                  <strong>Update</strong> status page for customer communication
                </Text>
              </li>
            </ol>
          </Section>

          {/* Status Page Link */}
          {statusPageUrl && (
            <Section style={statusSection}>
              <Button style={buttonSecondary} href={statusPageUrl}>
                Update Status Page
              </Button>
            </Section>
          )}

          {/* Dashboard Link */}
          <Section style={dashboardSection}>
            <Button style={buttonSecondary} href={dashboardUrl}>
              View Full Dashboard
            </Button>
          </Section>

          <Hr style={divider} />

          {/* Footer */}
          <Section style={footer}>
            <Text style={footerText}>
              <strong>Need help?</strong> Contact the SRE team via Slack
              <br />
              #incidents channel
            </Text>
            <Text style={footerSubtext}>
              This is an automated critical alert. Please respond immediately.
            </Text>
          </Section>
        </Container>
      </Body>
    </Html>
  );
};

export default IncidentEscalation;

// Styles
const main: React.CSSProperties = {
  backgroundColor: "#f6f9fc",
  fontFamily:
    '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Ubuntu,sans-serif',
  padding: "20px 0",
};

const container: React.CSSProperties = {
  backgroundColor: "#ffffff",
  margin: "0 auto",
  maxWidth: "600px",
  borderRadius: "8px",
  boxShadow: "0 4px 20px rgba(192, 57, 43, 0.2)",
  overflow: "hidden",
};

const header: React.CSSProperties = {
  padding: "24px 20px",
  textAlign: "center",
  borderBottom: "4px solid #a93226",
};

const badgeText: React.CSSProperties = {
  fontSize: "12px",
  fontWeight: "800",
  color: "#ffffff",
  textTransform: "uppercase",
  margin: "0 0 8px 0",
  letterSpacing: "1px",
};

const headerTitleText: React.CSSProperties = {
  fontSize: "22px",
  fontWeight: "700",
  color: "#ffffff",
  margin: "0 0 6px 0",
};

const headerSubtext: React.CSSProperties = {
  fontSize: "13px",
  color: "rgba(255, 255, 255, 0.8)",
  margin: "0",
};

const summarySection: React.CSSProperties = {
  padding: "16px 20px",
  backgroundColor: "#ecf0f1",
  borderBottom: "1px solid #bdc3c7",
};

const summaryBox: React.CSSProperties = {
  textAlign: "center",
  paddingRight: "12px",
};

const summaryLabel: React.CSSProperties = {
  fontSize: "11px",
  fontWeight: "700",
  color: "#7f8c8d",
  textTransform: "uppercase",
  margin: "0 0 4px 0",
};

const summaryValue: React.CSSProperties = {
  fontSize: "18px",
  fontWeight: "700",
  color: "#2c3e50",
  margin: "0",
};

const contentSection: React.CSSProperties = {
  padding: "20px",
  borderBottom: "1px solid #eaeaea",
};

const sectionTitle: React.CSSProperties = {
  fontSize: "16px",
  fontWeight: "700",
  color: "#2c3e50",
  margin: "0 0 12px 0",
  textTransform: "uppercase",
  borderBottom: "2px solid #3498db",
  paddingBottom: "8px",
};

const descriptionText: React.CSSProperties = {
  fontSize: "14px",
  color: "#1a1a1a",
  lineHeight: "1.6",
  margin: "0",
};

const serviceBox: React.CSSProperties = {
  backgroundColor: "#f8f9fa",
  padding: "12px",
  borderRadius: "6px",
  marginBottom: "10px",
  borderLeft: "4px solid #e74c3c",
};

const serviceName: React.CSSProperties = {
  fontSize: "14px",
  fontWeight: "600",
  color: "#2c3e50",
  margin: "0",
};

const serviceSubtext: React.CSSProperties = {
  fontSize: "12px",
  color: "#666",
  margin: "4px 0 0 0",
};

const statusBadge: React.CSSProperties = {
  fontSize: "11px",
  fontWeight: "700",
  color: "#ffffff",
  padding: "4px 8px",
  borderRadius: "4px",
  margin: "0",
  display: "inline-block",
};

const runbookSection: React.CSSProperties = {
  padding: "20px",
  backgroundColor: "#f0f8ff",
  borderBottom: "1px solid #eaeaea",
};

const runbookBox: React.CSSProperties = {
  backgroundColor: "#e8f4f8",
  padding: "16px",
  borderRadius: "6px",
  borderLeft: "4px solid #27ae60",
};

const runbookName: React.CSSProperties = {
  fontSize: "14px",
  fontWeight: "700",
  color: "#27ae60",
  margin: "0",
};

const runbookDetail: React.CSSProperties = {
  fontSize: "12px",
  color: "#555",
  margin: "0",
};

const runbookNote: React.CSSProperties = {
  fontSize: "12px",
  color: "#666",
  backgroundColor: "#ffffff",
  padding: "8px",
  borderRadius: "4px",
  margin: "12px 0",
};

const oncallBox: React.CSSProperties = {
  backgroundColor: "#f8f9fa",
  padding: "16px",
  borderRadius: "6px",
  borderLeft: "4px solid #9b59b6",
};

const oncallLabel: React.CSSProperties = {
  fontSize: "11px",
  fontWeight: "700",
  color: "#7f8c8d",
  textTransform: "uppercase",
  margin: "0 0 4px 0",
};

const oncallName: React.CSSProperties = {
  fontSize: "16px",
  fontWeight: "700",
  color: "#2c3e50",
  margin: "0",
};

const oncallEmail: React.CSSProperties = {
  fontSize: "13px",
  color: "#3498db",
  margin: "4px 0 12px 0",
};

const actionsSection: React.CSSProperties = {
  padding: "20px",
  backgroundColor: "#fdeaea",
  borderBottom: "1px solid #eaeaea",
  borderLeft: "4px solid #e74c3c",
};

const actionsTitle: React.CSSProperties = {
  fontSize: "13px",
  fontWeight: "800",
  color: "#c0392b",
  margin: "0 0 12px 0",
  letterSpacing: "0.5px",
};

const actionsList: React.CSSProperties = {
  margin: "0",
  paddingLeft: "20px",
};

const actionItem: React.CSSProperties = {
  fontSize: "13px",
  color: "#2c3e50",
  margin: "0 0 8px 0",
  lineHeight: "1.5",
};

const statusSection: React.CSSProperties = {
  padding: "16px 20px",
  textAlign: "center",
};

const dashboardSection: React.CSSProperties = {
  padding: "16px 20px",
  textAlign: "center",
  borderTop: "1px solid #eaeaea",
};

const buttonPrimary: React.CSSProperties = {
  backgroundColor: "#e74c3c",
  color: "#ffffff",
  padding: "12px 24px",
  borderRadius: "6px",
  textDecoration: "none",
  fontSize: "14px",
  fontWeight: "700",
  display: "inline-block",
  marginTop: "12px",
};

const buttonApprove: React.CSSProperties = {
  backgroundColor: "#27ae60",
  color: "#ffffff",
  padding: "12px 24px",
  borderRadius: "6px",
  textDecoration: "none",
  fontSize: "14px",
  fontWeight: "700",
  display: "inline-block",
  marginTop: "12px",
};

const buttonSecondary: React.CSSProperties = {
  backgroundColor: "#95a5a6",
  color: "#ffffff",
  padding: "10px 20px",
  borderRadius: "6px",
  textDecoration: "none",
  fontSize: "13px",
  fontWeight: "600",
  display: "inline-block",
};

const divider: React.CSSProperties = {
  borderColor: "#eaeaea",
  margin: "0",
};

const footer: React.CSSProperties = {
  padding: "20px",
  backgroundColor: "#2c3e50",
  textAlign: "center",
};

const footerText: React.CSSProperties = {
  fontSize: "12px",
  color: "#ecf0f1",
  margin: "0",
  lineHeight: "1.6",
};

const footerSubtext: React.CSSProperties = {
  fontSize: "11px",
  color: "#bdc3c7",
  margin: "8px 0 0 0",
};
