import React from "react";
import {
  Body,
  Button,
  Container,
  Head,
  Hr,
  Html,
  Img,
  Link,
  Preview,
  Row,
  Section,
  Text,
  Column,
} from "@react-email/components";

interface ResourceSummary {
  type: string;
  name: string;
  provider: string;
  provider_id: string;
  hourly_cost: number;
}

interface AccessUrl {
  name: string;
  url: string;
  username?: string;
}

interface ProvisioningCompleteProps {
  environmentName: string;
  requesterName: string;
  resources: ResourceSummary[];
  accessUrls: AccessUrl[];
  monthlyEstimate: number;
  ttlHours?: number;
  dashboardUrl: string;
  supportEmail: string;
}

export const ProvisioningComplete: React.FC<ProvisioningCompleteProps> = ({
  environmentName,
  requesterName,
  resources,
  accessUrls,
  monthlyEstimate,
  ttlHours = 720,
  dashboardUrl,
  supportEmail,
}) => {
  const expiryDate = new Date();
  expiryDate.setHours(expiryDate.getHours() + ttlHours);

  const severityColor = (cost: number) => {
    if (cost > 50) return "#ff6b6b";
    if (cost > 20) return "#ffa94d";
    return "#51cf66";
  };

  return (
    <Html>
      <Head />
      <Preview>Your infrastructure environment is ready: {environmentName}</Preview>
      <Body style={main}>
        <Container style={container}>
          {/* Header */}
          <Section style={header}>
            <Text style={headerText}>Infrastructure Automation Platform</Text>
          </Section>

          {/* Welcome */}
          <Section style={contentSection}>
            <Text style={greeting}>
              Hi {requesterName},
            </Text>
            <Text style={mainText}>
              Your infrastructure environment <strong>{environmentName}</strong> has been successfully provisioned and is ready to use!
            </Text>
          </Section>

          {/* Quick Stats */}
          <Section style={statsSection}>
            <Row>
              <Column style={statColumn}>
                <Text style={statValue}>{resources.length}</Text>
                <Text style={statLabel}>Resources</Text>
              </Column>
              <Column style={statColumn}>
                <Text style={statValue}>${monthlyEstimate.toFixed(2)}</Text>
                <Text style={statLabel}>Monthly Estimate</Text>
              </Column>
              <Column style={statColumn}>
                <Text style={statValue}>TTL: {ttlHours}h</Text>
                <Text style={statLabel}>
                  Expires: {expiryDate.toLocaleDateString()}
                </Text>
              </Column>
            </Row>
          </Section>

          {/* Resource Summary */}
          <Section style={contentSection}>
            <Text style={sectionTitle}>Provisioned Resources</Text>

            {resources.map((resource, idx) => (
              <Section key={idx} style={resourceBox}>
                <Row>
                  <Column style={{ width: "65%" }}>
                    <Text style={resourceName}>{resource.name}</Text>
                    <Text style={resourceType}>
                      {resource.type} on {resource.provider.toUpperCase()}
                    </Text>
                    <Text style={resourceId}>ID: {resource.provider_id}</Text>
                  </Column>
                  <Column style={{ width: "35%", textAlign: "right" }}>
                    <Text
                      style={{
                        ...costBadge,
                        backgroundColor: severityColor(resource.hourly_cost * 730),
                      }}
                    >
                      ${(resource.hourly_cost * 730).toFixed(2)}/mo
                    </Text>
                  </Column>
                </Row>
              </Section>
            ))}
          </Section>

          {/* Access URLs */}
          {accessUrls.length > 0 && (
            <Section style={contentSection}>
              <Text style={sectionTitle}>Access & Credentials</Text>

              {accessUrls.map((access, idx) => (
                <Section key={idx} style={accessBox}>
                  <Text style={accessLabel}>{access.name}</Text>
                  {access.username && (
                    <Text style={accessDetail}>
                      Username: <code style={codeStyle}>{access.username}</code>
                    </Text>
                  )}
                  <Button style={buttonPrimary} href={access.url}>
                    Open {access.name}
                  </Button>
                </Section>
              ))}

              <Text style={securityNote}>
                Store your credentials securely. Never share them via email or chat.
              </Text>
            </Section>
          )}

          {/* Important Info */}
          <Section style={warningBox}>
            <Text style={warningTitle}>Important Information</Text>
            <ul style={bulletList}>
              <li>
                <Text style={bulletItem}>
                  <strong>Expiration:</strong> This environment will be automatically
                  terminated on {expiryDate.toLocaleDateString()} at{" "}
                  {expiryDate.toLocaleTimeString()}
                </Text>
              </li>
              <li>
                <Text style={bulletItem}>
                  <strong>Cost:</strong> Estimated monthly cost is ${monthlyEstimate.toFixed(2)}
                </Text>
              </li>
              <li>
                <Text style={bulletItem}>
                  <strong>Support:</strong> Contact{" "}
                  <Link href={`mailto:${supportEmail}`}>{supportEmail}</Link> for issues
                </Text>
              </li>
              <li>
                <Text style={bulletItem}>
                  <strong>Health Checks:</strong> Monitor your environment at the{" "}
                  <Link href={dashboardUrl}>dashboard</Link>
                </Text>
              </li>
            </ul>
          </Section>

          {/* Next Steps */}
          <Section style={contentSection}>
            <Text style={sectionTitle}>Next Steps</Text>
            <ol style={numberList}>
              <li>
                <Text style={listItem}>
                  Verify all resources are accessible using the URLs above
                </Text>
              </li>
              <li>
                <Text style={listItem}>
                  Test your application or deployment pipeline
                </Text>
              </li>
              <li>
                <Text style={listItem}>
                  Monitor resource utilization in the dashboard
                </Text>
              </li>
              <li>
                <Text style={listItem}>
                  If you need to extend the TTL, request an extension before expiration
                </Text>
              </li>
            </ol>
          </Section>

          {/* CTA */}
          <Section style={ctaSection}>
            <Button style={buttonPrimary} href={dashboardUrl}>
              View Dashboard
            </Button>
          </Section>

          <Hr style={divider} />

          {/* Footer */}
          <Section style={footer}>
            <Text style={footerText}>
              Infrastructure Automation Platform
              <br />
              {supportEmail}
            </Text>
            <Text style={footerSubtext}>
              This is an automated message. Please do not reply to this email.
            </Text>
          </Section>
        </Container>
      </Body>
    </Html>
  );
};

export default ProvisioningComplete;

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
  boxShadow: "0 2px 12px rgba(0, 0, 0, 0.08)",
  overflow: "hidden",
};

const header: React.CSSProperties = {
  backgroundColor: "#2c3e50",
  padding: "20px",
  textAlign: "center",
  borderBottom: "4px solid #3498db",
};

const headerText: React.CSSProperties = {
  color: "#ffffff",
  fontSize: "24px",
  fontWeight: "600",
  margin: "0",
};

const contentSection: React.CSSProperties = {
  padding: "20px",
  borderBottom: "1px solid #eaeaea",
};

const greeting: React.CSSProperties = {
  fontSize: "16px",
  fontWeight: "600",
  color: "#2c3e50",
  margin: "0 0 10px 0",
};

const mainText: React.CSSProperties = {
  fontSize: "16px",
  color: "#1a1a1a",
  lineHeight: "1.6",
  margin: "0",
};

const sectionTitle: React.CSSProperties = {
  fontSize: "18px",
  fontWeight: "700",
  color: "#2c3e50",
  margin: "0 0 16px 0",
};

const statsSection: React.CSSProperties = {
  padding: "20px",
  backgroundColor: "#f0f7ff",
  borderBottom: "1px solid #eaeaea",
};

const statColumn: React.CSSProperties = {
  textAlign: "center",
  padding: "10px",
};

const statValue: React.CSSProperties = {
  fontSize: "24px",
  fontWeight: "700",
  color: "#3498db",
  margin: "0",
};

const statLabel: React.CSSProperties = {
  fontSize: "12px",
  color: "#666",
  margin: "4px 0 0 0",
  textTransform: "uppercase",
};

const resourceBox: React.CSSProperties = {
  backgroundColor: "#f8f9fa",
  padding: "12px",
  borderRadius: "6px",
  marginBottom: "12px",
  borderLeft: "4px solid #3498db",
};

const resourceName: React.CSSProperties = {
  fontSize: "14px",
  fontWeight: "600",
  color: "#2c3e50",
  margin: "0",
};

const resourceType: React.CSSProperties = {
  fontSize: "13px",
  color: "#666",
  margin: "4px 0",
};

const resourceId: React.CSSProperties = {
  fontSize: "11px",
  color: "#999",
  margin: "4px 0 0 0",
  fontFamily: "monospace",
};

const costBadge: React.CSSProperties = {
  fontSize: "14px",
  fontWeight: "600",
  color: "#ffffff",
  padding: "6px 12px",
  borderRadius: "4px",
  margin: "0",
  display: "inline-block",
};

const accessBox: React.CSSProperties = {
  backgroundColor: "#f8f9fa",
  padding: "16px",
  borderRadius: "6px",
  marginBottom: "12px",
  borderLeft: "4px solid #27ae60",
};

const accessLabel: React.CSSProperties = {
  fontSize: "14px",
  fontWeight: "600",
  color: "#2c3e50",
  margin: "0 0 8px 0",
};

const accessDetail: React.CSSProperties = {
  fontSize: "13px",
  color: "#666",
  margin: "0 0 12px 0",
};

const codeStyle: React.CSSProperties = {
  backgroundColor: "#ecf0f1",
  padding: "2px 6px",
  borderRadius: "3px",
  fontFamily: "monospace",
  fontSize: "12px",
};

const buttonPrimary: React.CSSProperties = {
  backgroundColor: "#3498db",
  color: "#ffffff",
  padding: "12px 24px",
  borderRadius: "6px",
  textDecoration: "none",
  fontSize: "14px",
  fontWeight: "600",
  display: "inline-block",
  marginTop: "8px",
};

const securityNote: React.CSSProperties = {
  fontSize: "12px",
  color: "#e74c3c",
  backgroundColor: "#fdeaea",
  padding: "8px 12px",
  borderRadius: "4px",
  margin: "0",
};

const warningBox: React.CSSProperties = {
  backgroundColor: "#fff3cd",
  borderLeft: "4px solid #ffc107",
  padding: "16px",
  margin: "0 20px 20px 20px",
  borderRadius: "4px",
};

const warningTitle: React.CSSProperties = {
  fontSize: "14px",
  fontWeight: "700",
  color: "#856404",
  margin: "0 0 12px 0",
};

const bulletList: React.CSSProperties = {
  margin: "0",
  paddingLeft: "20px",
};

const bulletItem: React.CSSProperties = {
  fontSize: "13px",
  color: "#333",
  lineHeight: "1.6",
  margin: "0 0 8px 0",
};

const numberList: React.CSSProperties = {
  margin: "0",
  paddingLeft: "20px",
};

const listItem: React.CSSProperties = {
  fontSize: "13px",
  color: "#333",
  lineHeight: "1.6",
  margin: "0 0 8px 0",
};

const ctaSection: React.CSSProperties = {
  padding: "20px",
  textAlign: "center",
};

const divider: React.CSSProperties = {
  borderColor: "#eaeaea",
  margin: "0",
};

const footer: React.CSSProperties = {
  padding: "20px",
  backgroundColor: "#f8f9fa",
};

const footerText: React.CSSProperties = {
  fontSize: "12px",
  color: "#666",
  textAlign: "center",
  margin: "0",
  lineHeight: "1.6",
};

const footerSubtext: React.CSSProperties = {
  fontSize: "11px",
  color: "#999",
  textAlign: "center",
  margin: "8px 0 0 0",
};
