#!/bin/bash
# mTLS Security Configuration for Lekiwi/XLE Robots
# Sets up mutual TLS authentication between robots and control server

set -e

# Configuration
CA_DIR="/etc/lekiwi/ca"
CERTS_DIR="/etc/lekiwi/certs"
KEYS_DIR="/etc/lekiwi/keys"
CSR_DIR="/etc/lekiwi/csr"
BACKUP_DIR="/etc/lekiwi/backup"
CA_KEY="${CA_DIR}/ca-key.pem"
CA_CERT="${CA_DIR}/ca-cert.pem"
CA_CONFIG="${CA_DIR}/ca.conf"
SERVER_CERT="${CERTS_DIR}/server-cert.pem"
SERVER_KEY="${KEYS_DIR}/server-key.pem"
CLIENT_CERT="${CERTS_DIR}/client-cert.pem"
CLIENT_KEY="${KEYS_DIR}/client-key.pem"

# Certificate validity periods
CA_DAYS=3650      # 10 years
CERT_DAYS=365     # 1 year
KEY_SIZE=4096     # RSA key size

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create directory structure
create_directories() {
    log_info "Creating certificate directories..."
    
    for dir in ${CA_DIR} ${CERTS_DIR} ${KEYS_DIR} ${CSR_DIR} ${BACKUP_DIR}; do
        mkdir -p ${dir}
        chmod 700 ${dir}
    done
    
    # Set restrictive permissions on key directories
    chmod 700 ${KEYS_DIR}
    chown -R root:root ${CA_DIR} ${KEYS_DIR}
}

# Generate Certificate Authority
generate_ca() {
    log_info "Generating Certificate Authority..."
    
    # Create CA configuration
    cat > ${CA_CONFIG} <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_ca
prompt = no

[req_distinguished_name]
C = US
ST = California
L = San Francisco
O = Lekiwi Robotics
OU = Robot CA
CN = Lekiwi Robot CA
emailAddress = ca@lekiwi.io

[v3_ca]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical,CA:true
keyUsage = critical,digitalSignature,cRLSign,keyCertSign

[v3_intermediate_ca]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical,CA:true,pathlen:0
keyUsage = critical,digitalSignature,cRLSign,keyCertSign

[server_cert]
basicConstraints = CA:FALSE
nsCertType = server
nsComment = "Lekiwi Robot Server Certificate"
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer:always
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth

[client_cert]
basicConstraints = CA:FALSE
nsCertType = client
nsComment = "Lekiwi Robot Client Certificate"
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer:always
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = clientAuth

[signing_policy]
countryName = optional
stateOrProvinceName = optional
localityName = optional
organizationName = optional
organizationalUnitName = optional
commonName = supplied
emailAddress = optional
EOF
    
    # Generate CA private key
    if [ ! -f ${CA_KEY} ]; then
        openssl genrsa -out ${CA_KEY} ${KEY_SIZE}
        chmod 400 ${CA_KEY}
        log_info "CA private key generated"
    else
        log_warn "CA private key already exists, skipping"
    fi
    
    # Generate CA certificate
    if [ ! -f ${CA_CERT} ]; then
        openssl req -new -x509 -days ${CA_DAYS} -key ${CA_KEY} \
            -out ${CA_CERT} -config ${CA_CONFIG}
        chmod 444 ${CA_CERT}
        log_info "CA certificate generated"
        
        # Display CA certificate info
        openssl x509 -in ${CA_CERT} -noout -text | head -20
    else
        log_warn "CA certificate already exists, skipping"
    fi
}

# Generate server certificate for control server
generate_server_cert() {
    local SERVER_NAME="${1:-control.lekiwi.io}"
    local SERVER_IP="${2:-192.168.100.1}"
    
    log_info "Generating server certificate for ${SERVER_NAME}..."
    
    # Create server certificate config
    cat > ${CSR_DIR}/server.conf <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = California
L = San Francisco
O = Lekiwi Robotics
OU = Control Server
CN = ${SERVER_NAME}

[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation,digitalSignature,keyEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${SERVER_NAME}
DNS.2 = *.lekiwi.local
DNS.3 = localhost
IP.1 = ${SERVER_IP}
IP.2 = 127.0.0.1
EOF
    
    # Generate server private key
    openssl genrsa -out ${SERVER_KEY} ${KEY_SIZE}
    chmod 400 ${SERVER_KEY}
    
    # Generate server CSR
    openssl req -new -key ${SERVER_KEY} -out ${CSR_DIR}/server.csr \
        -config ${CSR_DIR}/server.conf
    
    # Sign server certificate
    openssl x509 -req -in ${CSR_DIR}/server.csr \
        -CA ${CA_CERT} -CAkey ${CA_KEY} -CAcreateserial \
        -out ${SERVER_CERT} -days ${CERT_DAYS} \
        -extensions v3_req -extfile ${CSR_DIR}/server.conf
    
    chmod 444 ${SERVER_CERT}
    log_info "Server certificate generated"
}

# Generate client certificate for robot
generate_robot_cert() {
    local ROBOT_ID="${1}"
    local ROBOT_TYPE="${2:-unknown}"
    
    if [ -z "${ROBOT_ID}" ]; then
        ROBOT_ID=$(cat /proc/sys/kernel/random/uuid)
        log_info "Generated robot ID: ${ROBOT_ID}"
    fi
    
    log_info "Generating client certificate for robot ${ROBOT_ID}..."
    
    # Create client certificate config
    cat > ${CSR_DIR}/client.conf <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = California  
L = San Francisco
O = Lekiwi Robotics
OU = Robot Fleet
CN = robot-${ROBOT_ID}

[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation,digitalSignature,keyEncipherment
extendedKeyUsage = clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = robot-${ROBOT_ID}.lekiwi.local
URI.1 = urn:robot:${ROBOT_TYPE}:${ROBOT_ID}
EOF
    
    # Generate client private key
    openssl genrsa -out ${CLIENT_KEY} ${KEY_SIZE}
    chmod 400 ${CLIENT_KEY}
    chown lekiwi-agent:lekiwi-agent ${CLIENT_KEY} 2>/dev/null || true
    
    # Generate client CSR
    openssl req -new -key ${CLIENT_KEY} -out ${CSR_DIR}/client.csr \
        -config ${CSR_DIR}/client.conf
    
    # Sign client certificate
    openssl x509 -req -in ${CSR_DIR}/client.csr \
        -CA ${CA_CERT} -CAkey ${CA_KEY} -CAcreateserial \
        -out ${CLIENT_CERT} -days ${CERT_DAYS} \
        -extensions v3_req -extfile ${CSR_DIR}/client.conf
    
    chmod 444 ${CLIENT_CERT}
    chown lekiwi-agent:lekiwi-agent ${CLIENT_CERT} 2>/dev/null || true
    
    log_info "Client certificate generated for robot ${ROBOT_ID}"
    
    # Save robot ID for reference
    echo "${ROBOT_ID}" > ${CERTS_DIR}/robot-id
}

# Create certificate bundle for distribution
create_cert_bundle() {
    local BUNDLE_FILE="${1:-/tmp/robot-certs.tar.gz}"
    
    log_info "Creating certificate bundle..."
    
    # Create temporary directory
    local TEMP_DIR=$(mktemp -d)
    
    # Copy necessary files
    cp ${CA_CERT} ${TEMP_DIR}/ca-cert.pem
    cp ${CLIENT_CERT} ${TEMP_DIR}/client-cert.pem
    cp ${CLIENT_KEY} ${TEMP_DIR}/client-key.pem
    
    # Create bundle
    tar -czf ${BUNDLE_FILE} -C ${TEMP_DIR} .
    
    # Cleanup
    rm -rf ${TEMP_DIR}
    
    log_info "Certificate bundle created: ${BUNDLE_FILE}"
    
    # Generate installation script
    cat > ${BUNDLE_FILE%.tar.gz}-install.sh <<'INSTALL'
#!/bin/bash
# Certificate installation script for robots

CERTS_DIR="/etc/lekiwi/certs"
KEYS_DIR="/etc/lekiwi/keys"

# Extract certificates
mkdir -p ${CERTS_DIR} ${KEYS_DIR}
tar -xzf robot-certs.tar.gz -C /tmp/

# Install certificates
cp /tmp/ca-cert.pem ${CERTS_DIR}/
cp /tmp/client-cert.pem ${CERTS_DIR}/
cp /tmp/client-key.pem ${KEYS_DIR}/

# Set permissions
chmod 444 ${CERTS_DIR}/*.pem
chmod 400 ${KEYS_DIR}/*.pem
chown -R lekiwi-agent:lekiwi-agent ${CERTS_DIR} ${KEYS_DIR}

# Verify installation
openssl verify -CAfile ${CERTS_DIR}/ca-cert.pem ${CERTS_DIR}/client-cert.pem

echo "Certificates installed successfully"
INSTALL
    
    chmod +x ${BUNDLE_FILE%.tar.gz}-install.sh
}

# Setup certificate rotation
setup_cert_rotation() {
    log_info "Setting up certificate rotation..."
    
    # Create rotation script
    cat > /usr/local/bin/rotate-robot-cert.sh <<'ROTATE'
#!/bin/bash
# Certificate rotation script

source /etc/lekiwi/hardware.conf 2>/dev/null
source /etc/robot.conf 2>/dev/null

CERTS_DIR="/etc/lekiwi/certs"
KEYS_DIR="/etc/lekiwi/keys"
BACKUP_DIR="/etc/lekiwi/backup"

# Check certificate expiry
CERT_FILE="${CERTS_DIR}/client-cert.pem"
DAYS_LEFT=$(( ($(date -d "$(openssl x509 -in ${CERT_FILE} -noout -enddate | cut -d= -f2)" +%s) - $(date +%s)) / 86400 ))

if [ ${DAYS_LEFT} -lt 30 ]; then
    echo "Certificate expires in ${DAYS_LEFT} days, rotating..."
    
    # Backup current certificates
    mkdir -p ${BACKUP_DIR}
    timestamp=$(date +%Y%m%d_%H%M%S)
    cp ${CERT_FILE} ${BACKUP_DIR}/client-cert-${timestamp}.pem
    cp ${KEYS_DIR}/client-key.pem ${BACKUP_DIR}/client-key-${timestamp}.pem
    
    # Request new certificate from control server
    curl -X POST https://control.lekiwi.io:8443/api/cert/renew \
        --cert ${CERT_FILE} \
        --key ${KEYS_DIR}/client-key.pem \
        --cacert ${CERTS_DIR}/ca-cert.pem \
        -o /tmp/new-cert.pem
    
    if [ $? -eq 0 ]; then
        # Install new certificate
        mv /tmp/new-cert.pem ${CERT_FILE}
        
        # Restart agent to use new certificate
        systemctl restart lekiwi-agent.service
        
        echo "Certificate rotated successfully"
    else
        echo "Failed to rotate certificate"
        exit 1
    fi
else
    echo "Certificate valid for ${DAYS_LEFT} days"
fi
ROTATE
    
    chmod +x /usr/local/bin/rotate-robot-cert.sh
    
    # Create systemd timer for rotation
    cat > /etc/systemd/system/cert-rotation.timer <<EOF
[Unit]
Description=Certificate Rotation Timer
Requires=network-online.target

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF
    
    cat > /etc/systemd/system/cert-rotation.service <<EOF
[Unit]
Description=Certificate Rotation Service
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/rotate-robot-cert.sh
User=root
StandardOutput=journal
StandardError=journal
EOF
    
    systemctl daemon-reload
    systemctl enable cert-rotation.timer
}

# Configure nginx for mTLS
configure_nginx_mtls() {
    log_info "Configuring nginx for mTLS..."
    
    cat > /etc/nginx/sites-available/mtls <<EOF
server {
    listen 8443 ssl;
    server_name control.lekiwi.io;
    
    # SSL/TLS configuration
    ssl_certificate ${SERVER_CERT};
    ssl_certificate_key ${SERVER_KEY};
    
    # Client certificate verification
    ssl_client_certificate ${CA_CERT};
    ssl_verify_client on;
    ssl_verify_depth 2;
    
    # Strong SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    
    location / {
        # Pass client certificate info to backend
        proxy_set_header X-SSL-Client-Cert \$ssl_client_cert;
        proxy_set_header X-SSL-Client-S-DN \$ssl_client_s_dn;
        proxy_set_header X-SSL-Client-Verify \$ssl_client_verify;
        
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
    
    ln -sf /etc/nginx/sites-available/mtls /etc/nginx/sites-enabled/
    nginx -t && systemctl reload nginx
}

# Setup firewall rules
setup_firewall() {
    log_info "Setting up firewall rules..."
    
    # Install ufw if not present
    if ! command -v ufw &>/dev/null; then
        apt-get install -y ufw
    fi
    
    # Configure firewall
    ufw --force disable
    ufw default deny incoming
    ufw default allow outgoing
    
    # Allow SSH (rate limited)
    ufw limit 22/tcp
    
    # Allow mTLS port
    ufw allow 8443/tcp
    
    # Allow local agent API
    ufw allow from 127.0.0.1 to any port 8080
    
    # Enable firewall
    ufw --force enable
    
    log_info "Firewall configured"
}

# Verify certificate chain
verify_certificates() {
    log_info "Verifying certificate chain..."
    
    # Verify CA certificate
    openssl x509 -in ${CA_CERT} -noout -text | grep "CA:TRUE" &>/dev/null
    if [ $? -eq 0 ]; then
        log_info "✓ CA certificate valid"
    else
        log_error "✗ CA certificate invalid"
        return 1
    fi
    
    # Verify server certificate
    if [ -f ${SERVER_CERT} ]; then
        openssl verify -CAfile ${CA_CERT} ${SERVER_CERT}
        if [ $? -eq 0 ]; then
            log_info "✓ Server certificate valid"
        else
            log_error "✗ Server certificate invalid"
            return 1
        fi
    fi
    
    # Verify client certificate
    if [ -f ${CLIENT_CERT} ]; then
        openssl verify -CAfile ${CA_CERT} ${CLIENT_CERT}
        if [ $? -eq 0 ]; then
            log_info "✓ Client certificate valid"
        else
            log_error "✗ Client certificate invalid"
            return 1
        fi
    fi
    
    return 0
}

# Main setup flow
main() {
    log_info "Starting mTLS security setup..."
    
    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
    
    # Parse arguments
    MODE="${1:-robot}"  # robot or server
    ROBOT_ID="${2:-}"
    ROBOT_TYPE="${3:-}"
    
    # Load configuration if available
    [ -f /etc/robot.conf ] && source /etc/robot.conf
    [ -f /etc/lekiwi/hardware.conf ] && source /etc/lekiwi/hardware.conf
    
    # Create directory structure
    create_directories
    
    if [ "${MODE}" = "server" ]; then
        # Server mode: Generate CA and server certificates
        generate_ca
        generate_server_cert
        configure_nginx_mtls
        setup_firewall
        
        log_info "Server mTLS setup complete"
        log_info "CA certificate: ${CA_CERT}"
        log_info "Server certificate: ${SERVER_CERT}"
        
    elif [ "${MODE}" = "robot" ]; then
        # Robot mode: Generate client certificate
        if [ ! -f ${CA_CERT} ]; then
            log_error "CA certificate not found. Run server setup first or provide CA cert"
            exit 1
        fi
        
        generate_robot_cert "${ROBOT_ID}" "${ROBOT_TYPE}"
        setup_cert_rotation
        
        # Create certificate bundle for easy distribution
        create_cert_bundle
        
        log_info "Robot mTLS setup complete"
        log_info "Client certificate: ${CLIENT_CERT}"
        log_info "Certificate bundle: /tmp/robot-certs.tar.gz"
        
    else
        log_error "Invalid mode: ${MODE}. Use 'server' or 'robot'"
        exit 1
    fi
    
    # Verify certificates
    verify_certificates
    
    # Display summary
    echo ""
    echo "====================================="
    echo -e "${GREEN}mTLS Security Setup Complete!${NC}"
    echo "====================================="
    echo "Mode: ${MODE}"
    echo "Certificates directory: ${CERTS_DIR}"
    echo "Keys directory: ${KEYS_DIR}"
    echo "====================================="
}

# Run main function
if [ "${BASH_SOURCE[0]}" == "${0}" ]; then
    main "$@"
fi