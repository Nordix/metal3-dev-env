#!/bin/bash

OS_TYPE=${1:-centos}
SSH_PUB_KEY=${2:-~/.ssh/id_rsa.pub}

if [ -z "${SSH_PUB_KEY}" ] ; then
    echo "Usage: user_data.sh <secret name prefix> [os type]"
    echo
    echo '    os type: "centos", or "unknown" (default)'
    echo
    echo 'Expected env vars:'
    echo '    SSH_PUB_KEY - path to ssh public key'
    exit 1
fi

#
# Our virtual bare metal environment is created with two networks: NIC 1)
# "provisioning" NIC 2) "baremetal"
#
# cloud-init based images will only bring up the first network interface by
# default.  We need it to bring up our second interface, as well.
#
# TODO(russellb) - It would be nice to make this more dynamic and also not
# platform specific.  cloud-init knows how to read a network_data.json file
# from config drive.  Maybe we could have the baremetal-operator automatically
# generate a network_data.json file that says to do DHCP on all interfaces that
# we know about from introspection.
#
#--------------------cloud-init master------------------------------
cloud_init_master() {
if [ "$OS_TYPE" = "centos" ] ; then
cat << EOF

yum_repos:
    kubernetes:
        baseurl: https://packages.cloud.google.com/yum/repos/kubernetes-el7-x86_64
        enabled: 1
        gpgcheck: 1
        repo_gpgcheck: 1
        gpgkey: https://packages.cloud.google.com/yum/doc/yum-key.gpg https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg

runcmd:
  - [ ifup, eth1 ]
  - hostnamectl set-hostname master
  # Install updates
  - yum check-update

  # Install keepalived
  - yum install -y gcc kernel-headers kernel-devel
  - yum install -y keepalived
  - systemctl start keepalived
  - systemctl enable keepalived

  # Install docker
  - yum install -y yum-utils device-mapper-persistent-data lvm2
  - yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
  - yum install docker-ce docker-ce-cli containerd.io -y
  - usermod -aG docker centos
  - systemctl start docker
  - systemctl enable docker

  # Install, Init, Join kubernetes
  - setenforce 0
  - sed -i 's/^SELINUX=enforcing$/SELINUX=permissive/' /etc/selinux/config
  - yum install -y kubelet kubeadm kubectl --disableexcludes=kubernetes
  - systemctl enable --now kubelet
  - kubeadm init --token "rjptsr.83zrnxd8yhrnbp8l" --apiserver-advertise-address 192.168.111.249 -v 5
  - mkdir -p /home/centos/.kube
  - cp /etc/kubernetes/admin.conf /home/centos/.kube/config
  - chown centos:centos /home/centos/.kube/config
  - sleep 60
  - kubectl --kubeconfig=/home/centos/.kube/config apply -f https://raw.githubusercontent.com/coreos/flannel/2140ac876ef134e0ed5af15c65e414cf26827915/Documentation/kube-flannel.yml


# Useful for troubleshooting cloud-init issues
output: {all: '| tee -a /var/log/cloud-init-output.log'}

# keepalived Configuration file
write_files:
  - path: /etc/keepalived/keepalived.conf
    content: |
      ! Configuration File for keepalived

      global_defs {
         notification_email {
           sysadmin@mydomain.com
           support@mydomain.com
         }
         notification_email_from lb1@mydomain.com
         smtp_server localhost
         smtp_connect_timeout 30
      }

      vrrp_instance VI_1 {
          state MASTER
          interface eth0
          virtual_router_id 51
          priority 101
          advert_int 1
          authentication {
              auth_type PASS
              auth_pass 1111
          }
          virtual_ipaddress {
              192.168.111.249
          }
      }
  - path: /etc/sysconfig/network-scripts/ifcfg-eth1
    owner: root:root
    permissions: '0644'
    content: |
      BOOTPROTO=dhcp
      DEVICE=eth1
      ONBOOT=yes
      TYPE=Ethernet
      USERCTL=no
EOF
    fi
}
#--------------------cloud-init worker------------------------------
cloud_init_worker() {
if [ "$OS_TYPE" = "centos" ] ; then
cat << EOF

yum_repos:
    kubernetes:
        baseurl: https://packages.cloud.google.com/yum/repos/kubernetes-el7-x86_64
        enabled: 1
        gpgcheck: 1
        repo_gpgcheck: 1
        gpgkey: https://packages.cloud.google.com/yum/doc/yum-key.gpg https://packages.cloud.google.com/yum/doc/rpm-package-key.gpg

runcmd:
  - [ ifup, eth1 ]
  - hostnamectl set-hostname worker
  # Install updates
  - yum check-update

  # Install docker
  - yum install -y yum-utils device-mapper-persistent-data lvm2
  - yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
  - yum install docker-ce docker-ce-cli containerd.io -y
  - usermod -aG docker centos
  - systemctl start docker
  - systemctl enable docker

  # Install, Init, Join kubernetes
  - setenforce 0
  - sed -i 's/^SELINUX=enforcing$/SELINUX=permissive/' /etc/selinux/config
  - yum install -y kubelet kubeadm kubectl --disableexcludes=kubernetes
  - systemctl enable --now kubelet
  - kubeadm join 192.168.111.249:6443 --token "rjptsr.83zrnxd8yhrnbp8l" -v 5 --discovery-token-unsafe-skip-ca-verification

# Useful for troubleshooting cloud-init issues
output: {all: '| tee -a /var/log/cloud-init-output.log'}

# keepalived Configuration file
write_files:
  - path: /etc/sysconfig/network-scripts/ifcfg-eth1
    owner: root:root
    permissions: '0644'
    content: |
      BOOTPROTO=dhcp
      DEVICE=eth1
      ONBOOT=yes
      TYPE=Ethernet
      USERCTL=no
EOF
    fi
}

user_data_secret() {
    {
      printf "#cloud-config\n\nssh_authorized_keys:\n  - "
      cat "${SSH_PUB_KEY}"
      printf "\n"
      cloud_init_master
    } > ~/master-user-data.yaml
    {
      printf "#cloud-config\n\nssh_authorized_keys:\n  - "
      cat "${SSH_PUB_KEY}"
      printf "\n"
      cloud_init_worker
    } > ~/worker-user-data.yaml

}

user_data_secret
