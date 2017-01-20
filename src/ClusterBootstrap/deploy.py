import json
import os
import time
import datetime
import argparse
import uuid
import subprocess
import sys

import yaml
from jinja2 import Environment, FileSystemLoader, Template
import base64

from shutil import copyfile,copytree
import urllib

defanswer = ""

def firstChar(s):
	return (s.strip())[0].lower()
	

def raw_input_with_default(prompt):
	if defanswer == "":
		return raw_input(prompt)
	else:
		print prompt + " " + defanswer
		return defanswer

def render(template_file, target_file):
	ENV_local = Environment(loader=FileSystemLoader("/"))
	template = ENV_local.get_template(os.path.abspath(template_file))
	content = template.render(cnf=config)
	with open(target_file, 'w') as f:
		f.write(content)


def SSH_exec_cmd(identity_file, user,host,cmd):
	print ("""ssh -o "StrictHostKeyChecking no" -i %s "%s@%s" "%s" """ % (identity_file, user, host, cmd) ) 
	os.system("""ssh -o "StrictHostKeyChecking no" -i %s "%s@%s" "%s" """ % (identity_file, user, host, cmd) )

def SSH_connect(identity_file, user,host):
	print ("""ssh -o "StrictHostKeyChecking no" -i %s "%s@%s" """ % (identity_file, user, host) ) 
	os.system("""ssh -o "StrictHostKeyChecking no" -i %s "%s@%s" """ % (identity_file, user, host) )

def scp (identity_file, source, target, user, host):
	os.system('scp -i %s -r "%s" "%s@%s:%s"' % (identity_file, source, user, host, target) )

def sudo_scp (identity_file, source, target, user, host):
	tmp = str(uuid.uuid4())
	scp(identity_file, source,"~/%s" % tmp, user, host )
	SSH_exec_cmd(identity_file, user, host, "sudo mv ~/%s %s" % (tmp, target))



def Get_ETCD_DiscoveryURL(size):
		try:
			output = urllib.urlopen("https://discovery.etcd.io/new?size=%d" % size ).read()
			if not "https://discovery.etcd.io" in output:
				raise Exception("ERROR: we cannot get etcd discovery url from 'https://discovery.etcd.io/new?size=%d', got message %s" % (size,output)) 
		except Exception as e:
			raise Exception("ERROR: we cannot get etcd discovery url from 'https://discovery.etcd.io/new?size=%d'" % size) 
		return output

def _Check_Config_Items(cnfitem, cnf):
	if not cnfitem in cnf:
		raise Exception("ERROR: we cannot find %s in config file" % cnfitem) 
	else:
		print "Checking configurations '%s' = '%s'" % (cnfitem, cnf[cnfitem])
 
def Check_Config(cnf):
	_Check_Config_Items("discovery_url",cnf)
	_Check_Config_Items("kubernetes_master_node",cnf)
	_Check_Config_Items("kubernetes_master_ssh_user",cnf)
	_Check_Config_Items("api_serviers",cnf)
	_Check_Config_Items("etcd_user",cnf)
	_Check_Config_Items("etcd_node",cnf)
	_Check_Config_Items("etcd_endpoints",cnf)
	_Check_Config_Items("ssh_cert",cnf)
	_Check_Config_Items("pod_ip_range",cnf)
	_Check_Config_Items("basic_auth",cnf)
	_Check_Config_Items("kubernetes_docker_image",cnf)
	_Check_Config_Items("service_cluster_ip_range",cnf)
	if not os.path.isfile(config["ssh_cert"]):
		raise Exception("ERROR: we cannot find ssh key file at %s. \n please run 'python build-pxe-coreos.py docker_image_name' to generate ssh key file and pxe server image." % config["ssh_cert"]) 



def Gen_SSHKey():
		print "==============================================="
		print "generating ssh key..."
		os.system("mkdir -p ./deploy/sshkey")
		os.system("mkdir -p ./deploy/cloud-config")
		os.system("mkdir -p ./deploy/kubelet")
		os.system("rm -r ./deploy/sshkey || true")
		os.system("mkdir -p ./deploy/sshkey")

		os.system("ssh-keygen -t rsa -b 4096 -f ./deploy/sshkey/id_rsa -P ''")

		os.system("rm -r ./deploy/cloud-config")
		os.system("mkdir -p ./deploy/cloud-config")

		os.system("rm -r ./deploy/kubelet")
		os.system("mkdir -p ./deploy/kubelet")


		clusterID = str(uuid.uuid4()) 
		with open("./deploy/clusterID.yml", 'w') as f:
			f.write("clusterId : %s" % clusterID)
		f.close()

def Init_Deployment():
	if (os.path.isfile("./deploy/clusterID.yml")):

		response = raw_input_with_default("There is a cluster deployment in './deploy', do you want to keep the existing ssh key and CA certificates (y/n)?")
		if firstChar(response) == "n":
			Gen_SSHKey()
			Gen_CA_Certificates()
			Gen_Worker_Certificates()

	else:
		Gen_SSHKey()
		Gen_CA_Certificates()
		Gen_Worker_Certificates()

	if os.path.exists("./deploy/clusterID.yml"):
		f = open("./deploy/clusterID.yml")
		tmp = yaml.load(f)
		f.close()
		if "clusterId" in tmp:
			clusterID = tmp["clusterId"]
		f.close()

	f = open("./deploy/sshkey/id_rsa.pub")
	sshkey_public = f.read()
	f.close()



	print "Cluster Id is : %s" % clusterID 

	config["clusterId"] = clusterID
	config["sshkey"] = sshkey_public

	ENV = Environment(loader=FileSystemLoader("/"))

	template_file = "./template/cloud-config/cloud-config-master.yml"
	target_file = "./deploy/cloud-config/cloud-config-master.yml"
	template = ENV.get_template(os.path.abspath(template_file))
	config["role"] = "master"

	content = template.render(cnf=config)
	with open(target_file, 'w') as f:
		f.write(content)
	f.close()

	template_file = "./template/cloud-config/cloud-config-etcd.yml"
	target_file = "./deploy/cloud-config/cloud-config-etcd.yml"
	template = ENV.get_template(os.path.abspath(template_file))
	config["role"] = "etcd"

	content = template.render(cnf=config)
	with open(target_file, 'w') as f:
		f.write(content)
	f.close()	



	template_file = "./iso-creator/mkimg.sh.template"
	target_file = "./iso-creator/mkimg.sh"
	template = ENV.get_template(os.path.abspath(template_file))

	content = template.render(cnf=config)
	with open(target_file, 'w') as f:
		f.write(content)
	f.close()	



	with open("./ssl/ca/ca.pem", 'r') as f:
		content = f.read()
	config["ca.pem"] = base64.b64encode(content)

	with open("./ssl/kubelet/apiserver.pem", 'r') as f:
		content = f.read()
	config["apiserver.pem"] = base64.b64encode(content)
	config["worker.pem"] = base64.b64encode(content)

	with open("./ssl/kubelet/apiserver-key.pem", 'r') as f:
		content = f.read()
	config["apiserver-key.pem"] = base64.b64encode(content)
	config["worker-key.pem"] = base64.b64encode(content)


	renderfiles = []


	kubemaster_cfg_files = [f for f in os.listdir("./template/kubelet") if os.path.isfile(os.path.join("./template/kubelet", f))]
	for file in kubemaster_cfg_files:
		renderfiles.append((os.path.join("./template/kubelet", file),os.path.join("./deploy/kubelet", file)))

	for (template_file,target_file) in renderfiles:
		render(template_file,target_file)




	kubemaster_cfg_files = [f for f in os.listdir("./deploy/kubelet") if os.path.isfile(os.path.join("./deploy/kubelet", f))]
	for file in kubemaster_cfg_files:
		with open(os.path.join("./deploy/kubelet", file), 'r') as f:
			content = f.read()
		config[file] = base64.b64encode(content)



	template_file = "./template/cloud-config/cloud-config-kubelet.yml"
	target_file = "./deploy/cloud-config/cloud-config-kubelet.yml"
	template = ENV.get_template(os.path.abspath(template_file))

	content = template.render(cnf=config)
	with open(target_file, 'w') as f:
		f.write(content)
	f.close()	


def GetMasterNodes(clusterId):
	output = urllib.urlopen("http://dlws-clusterportal.westus.cloudapp.azure.com:5000/GetNodes?role=master&clusterId=%s" % clusterId ).read()
	output = json.loads(json.loads(output))
	Nodes = []
	NodesInfo = [node for node in output["nodes"] if "time" in node]
	for node in NodesInfo:
		if not node["hostIP"] in Nodes:
			Nodes.append(node["hostIP"])	
	config["kubernetes_master_node"] = Nodes
	return Nodes

def GetETCDNodes(clusterId):
	output = urllib.urlopen("http://dlws-clusterportal.westus.cloudapp.azure.com:5000/GetNodes?role=etcd&clusterId=%s" % clusterId ).read()
	output = json.loads(json.loads(output))
	Nodes = []
	NodesInfo = [node for node in output["nodes"] if "time" in node]
	for node in NodesInfo:
		if not node["hostIP"] in Nodes:
			Nodes.append(node["hostIP"])	
	config["etcd_node"] = Nodes
	return Nodes


def GetWorkerNodes(clusterId):
	output = urllib.urlopen("http://dlws-clusterportal.westus.cloudapp.azure.com:5000/GetNodes?role=worker&clusterId=%s" % clusterId ).read()
	output = json.loads(json.loads(output))
	Nodes = []
	NodesInfo = [node for node in output["nodes"] if "time" in node]
	for node in NodesInfo:
		if not node["hostIP"] in Nodes:
			Nodes.append(node["hostIP"])	
	config["worker_node"] = Nodes
	return Nodes	

def Check_Master_ETCD_Status():
	masterNodes = []
	etcdNodes = []
	if "clusterId" in config:
		masterNodes = GetMasterNodes(config["clusterId"])
		etcdNodes = GetETCDNodes(config["clusterId"])

	print "Activate Master Node(s): %s\n %s \n" % (len(masterNodes),",".join(masterNodes))
	print "Activate ETCD Node(s):%s\n %s \n" % (len(etcdNodes),",".join(etcdNodes))

def Clean_Deployment():
	print "==============================================="
	print "Cleaning previous deployment..."	
	os.system("rm -r ./deploy/*")


def Gen_CA_Certificates():
	os.system("cd ./ssl && ./gencerts_ca.sh")

def Gen_Worker_Certificates():
	os.system("cd ./ssl && ./gencerts_kubelet.sh")	

def Gen_Master_Certificates():
	config["apiserver_ssl_dns"] = ""
	config["apiserver_ssl_ip"] = "IP.1 = 10.3.0.1\nIP.2 = 127.0.0.1\n"+ "\n".join(["IP."+str(i+3)+" = "+ip for i,ip in enumerate(config["kubernetes_master_node"])])

	renderfiles = []
	renderfiles.append(("./ssl/openssl-apiserver.cnf.template","./ssl/openssl-apiserver.cnf"))

	
	for (template_file,target_file) in renderfiles:
		render(template_file,target_file)

	os.system("cd ./ssl && ./gencerts_master.sh")


def Gen_ETCD_Certificates():

	config["etcd_ssl_dns"] = ""
	config["etcd_ssl_ip"] = "IP.1 = 127.0.0.1\n" + "\n".join(["IP."+str(i+2)+" = "+ip for i,ip in enumerate(config["etcd_node"])])
	renderfiles = []
	renderfiles.append(("./ssl/openssl-etcd.cnf.template","./ssl/openssl-etcd.cnf"))

	
	for (template_file,target_file) in renderfiles:
		render(template_file,target_file)

	os.system("cd ./ssl && ./gencerts_etcd.sh")	



def Gen_Configs():
	print "==============================================="
	print "generating configuration files..."
	os.system("mkdir -p ./deploy/bin")
	os.system("mkdir -p ./deploy/etcd")
	os.system("mkdir -p ./deploy/kube-addons")
	os.system("mkdir -p ./deploy/master")	
	os.system("rm -r ./deploy/bin")
	os.system("rm -r ./deploy/etcd")
	os.system("rm -r ./deploy/kube-addons")
	os.system("rm -r ./deploy/master")

	deployDirs = ["deploy/etcd","deploy/kubelet","deploy/master","deploy/web-docker/kubelet","deploy/kube-addons","deploy/bin"]
	for deployDir in deployDirs:
		if not os.path.exists(deployDir):
			os.system("mkdir -p %s" % (deployDir))


	etcd_servers = config["etcd_node"]

	if int(config["etcd_node_num"]) <= 0:
		raise Exception("ERROR: we need at least one etcd_server.") 

	kubernetes_masters = config["kubernetes_master_node"]

	if len(kubernetes_masters) <= 0:
		raise Exception("ERROR: we need at least one etcd_server.") 

	config["discovery_url"] = Get_ETCD_DiscoveryURL(int(config["etcd_node_num"]))

	if "ssh_cert" not in config and os.path.isfile("./deploy/sshkey/id_rsa"):
		config["ssh_cert"] = "./deploy/sshkey/id_rsa"
		config["etcd_user"] = "core"
		config["kubernetes_master_ssh_user"] = "core"

	#config["api_serviers"] = ",".join(["https://"+x for x in config["kubernetes_master_node"]])
	config["api_serviers"] = "https://"+config["kubernetes_master_node"][0]
	config["etcd_endpoints"] = ",".join(["https://"+x+":2379" for x in config["etcd_node"]])


	f = open(config["ssh_cert"])
	sshkey_public = f.read()
	f.close()

	config["sshkey"] = sshkey_public
	Check_Config(config)


	renderfiles = []

	kubemaster_cfg_files = [f for f in os.listdir("./template/etcd") if os.path.isfile(os.path.join("./template/etcd", f))]
	for file in kubemaster_cfg_files:
		renderfiles.append((os.path.join("./template/etcd", file),os.path.join("./deploy/etcd", file)))


	kubemaster_cfg_files = [f for f in os.listdir("./template/master") if os.path.isfile(os.path.join("./template/master", f))]
	for file in kubemaster_cfg_files:
		renderfiles.append((os.path.join("./template/master", file),os.path.join("./deploy/master", file)))


	kubemaster_cfg_files = [f for f in os.listdir("./template/web-docker") if os.path.isfile(os.path.join("./template/web-docker", f))]
	for file in kubemaster_cfg_files:
		renderfiles.append((os.path.join("./template/web-docker", file),os.path.join("./deploy/web-docker", file)))


	kubemaster_cfg_files = [f for f in os.listdir("./template/kube-addons") if os.path.isfile(os.path.join("./template/kube-addons", f))]
	for file in kubemaster_cfg_files:
		renderfiles.append((os.path.join("./template/kube-addons", file),os.path.join("./deploy/kube-addons", file)))


	
	for (template_file,target_file) in renderfiles:
		render(template_file,target_file)



def Update_Reporting_service():
	kubernetes_masters = config["kubernetes_master_node"]
	kubernetes_master_user = "core"

	for kubernetes_master in kubernetes_masters:
		print "==============================================="
		print "Updating report service on master %s... " % kubernetes_master

		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo systemctl stop reportcluster")
		scp(config["ssh_cert"],"./deploy/master/report.sh","/home/%s/report.sh" % kubernetes_master_user , kubernetes_master_user, kubernetes_master )
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mv /home/%s/report.sh /opt/report.sh" % (kubernetes_master_user))

		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo systemctl start reportcluster")


	etcd_servers = config["etcd_node"]
	etcd_server_user = "core"


	for etcd_server_address in etcd_servers:
		print "==============================================="
		print "Updating report service on etcd node %s... " % etcd_server_address

		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "sudo systemctl stop reportcluster")
		scp(config["ssh_cert"],"./deploy/etcd/report.sh","/home/%s/report.sh" % etcd_server_user , etcd_server_user, etcd_server_address )
		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "sudo mv /home/%s/report.sh /opt/report.sh" % (etcd_server_user))

		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "sudo systemctl start reportcluster")



def Deploy_Master():
	kubernetes_masters = config["kubernetes_master_node"]
	kubernetes_master_user = "core"

	for i,kubernetes_master in enumerate(kubernetes_masters):
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo hostnamectl set-hostname %s" % config["cluster_name"]+"-master"+str(i+1))


	for kubernetes_master in kubernetes_masters:
		print "==============================================="
		print "Clean up kubernetes master %s... (It is OK to see 'Errors' in this section)" % kubernetes_master


		exec_cmd_list = ["sudo systemctl stop kubelet", "docker rm -f \$(docker ps -q -a)", "sudo systemctl stop flanneld","sudo systemctl stop docker"]

		for exec_cmd in exec_cmd_list:
			SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, exec_cmd)

		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/kubernetes")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/systemd/system/flanneld.service.d")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/systemd/system/docker.service.d")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/flannel")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/ssl/etcd")

		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo rm -r /etc/kubernetes")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo rm -r /etc/ssl/etcd")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo rm -r /etc/systemd/system/flanneld.service.d")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo rm -r /etc/systemd/system/docker.service.d")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo rm -r /etc/flannel")


	for kubernetes_master in kubernetes_masters:
		print "==============================================="
		print "starting kubernetes master on %s..." % kubernetes_master


		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/kubernetes")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/systemd/system/flanneld.service.d")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/systemd/system/docker.service.d")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/flannel")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/kubernetes/manifests")

		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo chown -R %s /etc/kubernetes" % kubernetes_master_user)
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo chown -R %s /etc/flannel" % kubernetes_master_user)

		scp(config["ssh_cert"],"./ssl/apiserver","/etc/kubernetes/ssl", kubernetes_master_user, kubernetes_master )


		scp(config["ssh_cert"],"./ssl/apiserver","/home/%s/" % kubernetes_master_user, kubernetes_master_user, kubernetes_master )
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /etc/ssl/etcd")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mv /home/%s/apiserver/* /etc/ssl/etcd/" % (kubernetes_master_user))


		scp(config["ssh_cert"],"./deploy/master/basicauth","/etc/kubernetes/", kubernetes_master_user, kubernetes_master )

		

		sudo_scp(config["ssh_cert"],"./deploy/master/worker-kubeconfig.yaml","/etc/kubernetes/worker-kubeconfig.yaml", kubernetes_master_user, kubernetes_master )


		scp(config["ssh_cert"],"./deploy/master/40-ExecStartPre-symlink.conf","/home/%s/40-ExecStartPre-symlink.conf" % kubernetes_master_user, kubernetes_master_user, kubernetes_master )
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mv /home/%s/40-ExecStartPre-symlink.conf /etc/systemd/system/flanneld.service.d/40-ExecStartPre-symlink.conf" % (kubernetes_master_user))


		scp(config["ssh_cert"],"./deploy/master/40-flannel.conf","/home/%s/40-flannel.conf" % kubernetes_master_user, kubernetes_master_user, kubernetes_master )
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mv /home/%s/40-flannel.conf /etc/systemd/system/docker.service.d/40-flannel.conf" % (kubernetes_master_user))


		scp(config["ssh_cert"],"./deploy/master/options.env","/home/%s/options.env" % kubernetes_master_user , kubernetes_master_user, kubernetes_master )
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mv /home/%s/options.env /etc/flannel/options.env" % (kubernetes_master_user))


		config["master_ip"] = kubernetes_master
		render("./template/master/kube-apiserver.yaml","./deploy/master/kube-apiserver.yaml")
		render("./template/master/kubelet.service","./deploy/master/kubelet.service")


		scp(config["ssh_cert"],"./deploy/master/kubelet.service","/home/%s/kubelet.service" % kubernetes_master_user , kubernetes_master_user, kubernetes_master )
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mv /home/%s/kubelet.service /etc/systemd/system/kubelet.service" % (kubernetes_master_user))

		filelist = ["kube-apiserver.yaml", "kube-controller-manager.yaml", "kube-scheduler.yaml"]
		for file in filelist:
			scp(config["ssh_cert"],"./deploy/master/"+file,"/etc/kubernetes/manifests/"+file, kubernetes_master_user, kubernetes_master )


		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /opt/bin")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo chown -R %s /opt/bin" % kubernetes_master_user)
	
		urllib.urlretrieve ("http://ccsdatarepo.westus.cloudapp.azure.com/data/kube/kubelet/kubelet", "./deploy/bin/kubelet")
		urllib.urlretrieve ("http://ccsdatarepo.westus.cloudapp.azure.com/data/kube/kubelet/kubectl", "./deploy/bin/kubectl")


		scp(config["ssh_cert"],"./deploy/bin/kubelet","/opt/bin", kubernetes_master_user, kubernetes_master )
		scp(config["ssh_cert"],"./deploy/bin/kubectl","/opt/bin", kubernetes_master_user, kubernetes_master )

		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo chmod +x /opt/bin/*")

		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo mkdir -p /opt/addons")
		SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, "sudo chown -R %s /opt/addons" % kubernetes_master_user)
		scp(config["ssh_cert"],"./deploy/kube-addons","/opt/addons", kubernetes_master_user, kubernetes_master )


		exec_cmd_list = ["sudo systemctl daemon-reload","sudo systemctl stop flanneld","sudo systemctl stop kubelet","sudo systemctl start flanneld", "sudo systemctl stop docker", "sudo systemctl start docker", "sudo systemctl start kubelet", "sudo systemctl start rpc-statd", "sudo systemctl enable flanneld", "sudo systemctl enable kubelet"]
		for exec_cmd in exec_cmd_list:
			SSH_exec_cmd(config["ssh_cert"], kubernetes_master_user, kubernetes_master, exec_cmd)


def Deploy_ETCD():
	etcd_servers = config["etcd_node"]
	etcd_server_user = "core"

	for i,etcd_server_address in enumerate(etcd_servers):
		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "sudo hostnamectl set-hostname %s" % config["cluster_name"]+"-etcd"+str(i+1))

	for etcd_server_address in etcd_servers:
		print "==============================================="
		print "Clean up etcd servers %s... (It is OK to see 'Errors' in this section)" % etcd_server_address		
		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "docker rm -f \$(docker ps -q -a)")
		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "sudo rm -r /var/etcd/data")
		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "sudo rm -r /etc/kubernetes")



	for etcd_server_address in etcd_servers:
		#print "==============================================="
		#print "deploy configuration files to web server..."
		#scp(config["ssh_cert"],"./deploy","/var/www/html", config["webserver_user"], config["webserver"] )

		print "==============================================="
		print "deploy certificates to etcd server %s" % etcd_server_address
		
		SSH_exec_cmd (config["ssh_cert"], etcd_server_user, etcd_server_address, "sudo mkdir -p /etc/kubernetes/ssl") 
		SSH_exec_cmd (config["ssh_cert"], etcd_server_user, etcd_server_address, "sudo chown %s /etc/kubernetes/ssl " % (etcd_server_user)) 
		scp(config["ssh_cert"],"./ssl/etcd","/etc/kubernetes/ssl", etcd_server_user, etcd_server_address )

		print "==============================================="
		print "starting etcd service on %s ..." % etcd_server_address


		config["etcd_node_ip"] = etcd_server_address
		render("./template/etcd/docker_etcd.sh","./deploy/etcd/docker_etcd.sh")
		render("./template/etcd/docker_etcd_ssl.sh","./deploy/etcd/docker_etcd_ssl.sh")

		scp(config["ssh_cert"],"./deploy/etcd/docker_etcd.sh","/home/%s/docker_etcd.sh" % etcd_server_user, etcd_server_user, etcd_server_address )
		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "chmod +x /home/%s/docker_etcd.sh" % etcd_server_user)

		scp(config["ssh_cert"],"./deploy/etcd/docker_etcd_ssl.sh","/home/%s/docker_etcd_ssl.sh" % etcd_server_user, etcd_server_user, etcd_server_address )
		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "chmod +x /home/%s/docker_etcd_ssl.sh" % etcd_server_user)


		scp(config["ssh_cert"],"./deploy/etcd/init_network.sh","/home/%s/init_network.sh" % etcd_server_user, etcd_server_user, etcd_server_address )
		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "chmod +x /home/%s/init_network.sh" % etcd_server_user)

		SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_server_address, "/home/%s/docker_etcd_ssl.sh" % etcd_server_user)

	print "==============================================="
	print "init etcd service on %s ..."  % etcd_servers[0]


	print "waiting for ETCD service is ready..."
	cmd = "curl --cacert %s --cert %s --key %s 'https://%s:2379/v2/keys'" % ("./ssl/etcd/ca.pem","./ssl/etcd/etcd.pem","./ssl/etcd/etcd-key.pem", etcd_servers[0])
	while os.system(cmd) != 0:
		time.sleep(5)
	print "ETCD service is ready to use..."


	scp(config["ssh_cert"],"./deploy/etcd/init_network.sh","/home/%s/init_network.sh" % etcd_server_user, etcd_server_user, etcd_server_address )
	SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_servers[0], "chmod +x /home/%s/init_network.sh" % etcd_server_user)
	SSH_exec_cmd(config["ssh_cert"], etcd_server_user, etcd_servers[0], "/home/%s/init_network.sh" % etcd_server_user)


def Create_ISO():
	imagename = "./deploy/iso/dlworkspace-cluster-deploy-"+config["cluster_name"]+".iso"
	os.system("mkdir -p ./deploy/iso")
	os.system("cd iso-creator && bash ./mkimg.sh -v 1185.5.0 -a")
	os.system("mv ./iso-creator/coreos-1185.5.0.iso "+imagename )
	os.system("rm -rf ./iso-creator/syslinux-6.03*")
	os.system("rm -rf ./iso-creator/coreos-*")
	print "Please find the bootable USB image at: "+imagename
	print 


def Create_PXE():
	os.system("rm -r ./deploy/pxe")
	os.system("mkdir -p ./deploy/docker")
	os.system("cp -r ./template/pxe ./deploy/pxe")
	os.system("cp -r ./deploy/cloud-config/* ./deploy/pxe/tftp/usr/share/oem")
	dockername = "dlworkspace-pxe:%s" % config["cluster_name"] 
	os.system("docker build -t %s deploy/pxe" % dockername)
	tarname = "deploy/docker/dlworkspace-pxe-%s.tar" % config["cluster_name"]
	
	os.system("docker save " + dockername + " > " + tarname )
	print ("A DL workspace docker is built at: "+ dockername)
	print ("It is also saved as a tar file to: "+ tarname)
	
	#os.system("docker rmi dlworkspace-pxe:%s" % config["cluster_name"])

def CleanWorkerNodes():
	workerNodes = GetWorkerNodes(config["clusterId"])
	for nodeIP in workerNodes:
		print "==============================================="
		print "cleaning worker node: %s ..."  % nodeIP		
		SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl stop kubelet")
		SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "docker rm -f \$(docker ps -a -q)")
		SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl stop docker")
		SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl stop flanneld")
		SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl stop bootstrap")
		SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl stop reportcluster")
		SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo reboot")



def UpdateWorkerNode(nodeIP):
	print "==============================================="
	print "updating worker node: %s ..."  % nodeIP
	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl stop kubelet")
	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "docker rm -f \$(docker ps -a -q)")
	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl stop docker")
	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl stop flanneld")
	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl stop bootstrap")
	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl stop reportcluster")
	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo rm /etc/kubernetes/manifests/kube-proxy.yaml")



	sudo_scp(config["ssh_cert"],"./deploy/kubelet/options.env","/etc/flannel/options.env", "core", nodeIP )

	sudo_scp(config["ssh_cert"],"./deploy/kubelet/kubelet.service","/etc/systemd/system/kubelet.service", "core", nodeIP )

	sudo_scp(config["ssh_cert"],"./deploy/kubelet/worker-kubeconfig.yaml","/etc/kubernetes/worker-kubeconfig.yaml", "core", nodeIP )
	
	sudo_scp(config["ssh_cert"],"./deploy/kubelet/kubelet.sh","/opt/kubelet.sh", "core", nodeIP )

	sudo_scp(config["ssh_cert"],"./deploy/bin/kubelet","/opt/kubelet", "core", nodeIP )


	with open("./ssl/ca/ca.pem", 'r') as f:
		content = f.read()
	config["ca.pem"] = base64.b64encode(content)

	with open("./ssl/kubelet/apiserver.pem", 'r') as f:
		content = f.read()
	config["apiserver.pem"] = base64.b64encode(content)
	config["worker.pem"] = base64.b64encode(content)

	with open("./ssl/kubelet/apiserver-key.pem", 'r') as f:
		content = f.read()
	config["apiserver-key.pem"] = base64.b64encode(content)
	config["worker-key.pem"] = base64.b64encode(content)


	sudo_scp(config["ssh_cert"],"./ssl/ca/ca.pem","/etc/kubernetes/ssl/ca.pem", "core", nodeIP )
	sudo_scp(config["ssh_cert"],"./ssl/ca/ca.pem","/etc/ssl/etcd/ca.pem", "core", nodeIP )

	sudo_scp(config["ssh_cert"],"./ssl/kubelet/apiserver.pem","/etc/kubernetes/ssl/worker.pem", "core", nodeIP )
	sudo_scp(config["ssh_cert"],"./ssl/kubelet/apiserver.pem","/etc/ssl/etcd/apiserver.pem", "core", nodeIP )

	sudo_scp(config["ssh_cert"],"./ssl/kubelet/apiserver-key.pem","/etc/kubernetes/ssl/worker-key.pem", "core", nodeIP )
	sudo_scp(config["ssh_cert"],"./ssl/kubelet/apiserver-key.pem","/etc/ssl/etcd/apiserver-key.pem", "core", nodeIP )

	sudo_scp(config["ssh_cert"],"./deploy/kubelet/report.sh","/opt/report.sh", "core", nodeIP )
	sudo_scp(config["ssh_cert"],"./deploy/kubelet/reportcluster.service","/etc/systemd/system/reportcluster.service", "core", nodeIP )


	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl daemon-reload")

	#SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl start bootstrap")
	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl start flanneld")
	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl start docker")

	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl start kubelet")

	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl start reportcluster")
	SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo systemctl enable reportcluster")



	#SSH_exec_cmd(config["ssh_cert"], "core", nodeIP, "sudo journalctl -u kubelet")
	print "done!"


def UpdateWorkerNodes():
	os.system('sed "s/##etcd_endpoints##/%s/" "./deploy/kubelet/options.env.template" > "./deploy/kubelet/options.env"' % config["etcd_endpoints"].replace("/","\\/"))
	os.system('sed "s/##api_serviers##/%s/" ./deploy/kubelet/kubelet.service.template > ./deploy/kubelet/kubelet.service' % config["api_serviers"].replace("/","\\/"))
	os.system('sed "s/##api_serviers##/%s/" ./deploy/kubelet/worker-kubeconfig.yaml.template > ./deploy/kubelet/worker-kubeconfig.yaml' % config["api_serviers"].replace("/","\\/"))
	
	urllib.urlretrieve ("http://ccsdatarepo.westus.cloudapp.azure.com/data/kube/kubelet/kubelet", "./deploy/bin/kubelet")

	workerNodes = GetWorkerNodes(config["clusterId"])
	for node in workerNodes:
		UpdateWorkerNode(node)

	os.system("rm ./deploy/kubelet/options.env")
	os.system("rm ./deploy/kubelet/kubelet.service")
	os.system("rm ./deploy/kubelet/worker-kubeconfig.yaml")

	#if len(config["kubernetes_master_node"]) > 0:
		#SSH_exec_cmd(config["ssh_cert"], "core", config["kubernetes_master_node"][0], "sudo /opt/bin/kubelet get nodes")


def printUsage():
	print "Usage: python deploy.py COMMAND [Options] "
	print "  Build and deploy a DL workspace cluster. "
	print ""

	print "Prerequest:"
	print "  * Create config.yaml according to instruction in docs/deployment/Configuration.md"
	print ""
	print "Options:"
	print "    -y        Answer yes automatically for all prompt "
	
	print "Commands:"
	print "    build     Build USB iso/pxe-server used by deployment"
	print "    deploy    Deploy DL workspace cluster"
	print "    clean     Clean away a failed deployment. "
	print "    connect [master|etcd|worker] num: Connect to either master, etcd or worker node (with an index number) "


if __name__ == '__main__':
	config_file = os.path.join(os.path.dirname(os.path.realpath(__file__)),"config.yaml")
	if not os.path.exists(config_file):
		printUsage()
		print "ERROR: config.yaml does not exist!"
		exit()

	f = open(config_file)
	config = yaml.load(f)
	f.close()
	if os.path.exists("./deploy/clusterID.yml"):
		f = open("./deploy/clusterID.yml")
		tmp = yaml.load(f)
		f.close()
		if "clusterId" in tmp:
			config["clusterId"] = tmp["clusterId"]
	if "-y" in sys.argv:
		defanswer = "yes"
		sys.argv.remove("-y")
	if len(sys.argv) >= 2:
		if sys.argv[1] =="clean":
			Clean_Deployment()
			exit()
		elif sys.argv[1] == "build":
			command = "build"
		elif sys.argv[1] == "deploy":
			command = "deploy"
		elif sys.argv[1] == "updateworker":
			command = "updateworker"
		elif sys.argv[1] == "updatereport":
			command = "updatereport"
		elif sys.argv[1] == "cleanworker":
			command = "cleanworker"

			
		elif sys.argv[1] == "connect":
			if len(sys.argv) <= 2 or sys.argv[2] == "master":
				nodes = GetMasterNodes(config["clusterId"])
			elif sys.argv[2] == "etcd":
				nodes = GetETCDNodes(config["clusterId"])
			elif sys.argv[2] == "worker":
				nodes = GetWorkerNodes(config["clusterId"])
			else:
				printUsage()
				print "ERROR: must connect to either master, etcd or worker nodes"
				exit()
			if len(nodes) == 0:
				printUsage()
				print "ERROR: cannot find any node of the type to connect to"
				exit()
			num = 0
			if len(sys.argv) >= 4:
				num = int(sys.argv[3])
				if num < 0 or num >= len(nodes):
					num = 0
			nodename = nodes[num]
			SSH_connect( "./deploy/sshkey/id_rsa", "core", nodename)
			exit()
		else:
			printUsage()
			exit()

	if command == "deploy" and "clusterId" in config:
		print "Detected previous cluster deployment, cluster ID: %s. \n To clean up the previous deployment, run 'python deploy.py clean' \n" % config["clusterId"]
		print "The current deployment has:\n"
		
		Check_Master_ETCD_Status()

		if "etcd_node" in config and len(config["etcd_node"]) >= int(config["etcd_node_num"]) and "kubernetes_master_node" in config and len(config["kubernetes_master_node"]) >= 1:
			print "Ready to deploy kubernetes master on %s, etcd cluster on %s.  " % (",".join(config["kubernetes_master_node"]), ",".join(config["etcd_node"]))
			Gen_Configs()
			response = raw_input_with_default("Deploy ETCD Nodes (y/n)?")
			if response.strip() == "y":
				Gen_ETCD_Certificates()
				Deploy_ETCD()			
			response = raw_input_with_default("Deploy Master Nodes (y/n)?")
			if firstChar(response) == "y":
				Gen_Master_Certificates()
				Deploy_Master()

			response = raw_input_with_default("Allow Workers to register (y/n)?")
			if firstChar(response) == "y":

				urllib.urlretrieve ("http://dlws-clusterportal.westus.cloudapp.azure.com:5000/SetClusterInfo?clusterId=%s&key=etcd_endpoints&value=%s" %  (config["clusterId"],config["etcd_endpoints"]))
				urllib.urlretrieve ("http://dlws-clusterportal.westus.cloudapp.azure.com:5000/SetClusterInfo?clusterId=%s&key=api_server&value=%s" % (config["clusterId"],config["api_serviers"]))
			
#			response = raw_input_with_default("Create ISO file for deployment (y/n)?")
#			if firstChar(response) == "y":
#				Create_ISO()

#			response = raw_input_with_default("Create PXE docker image for deployment (y/n)?")
#			if firstChar(response) == "y":
#				Create_PXE()

		else:
			print "Cannot deploy cluster since there are insufficient number of etcd server or master server. \n To continue deploy the cluster we need at least %d etcd server(s) and 1 master server" % (int(config["etcd_node_num"]))
	elif command == "build":
		Init_Deployment()
		response = raw_input_with_default("Create ISO file for deployment (y/n)?")
		if firstChar(response) == "y":
			Create_ISO()
		response = raw_input_with_default("Create PXE docker image for deployment (y/n)?")
		if firstChar(response) == "y":
			Create_PXE()
	elif command == "updateworker":
		response = raw_input_with_default("Deploy Worker Nodes (y/n)?")
		if firstChar(response) == "y":
			Check_Master_ETCD_Status()
			Gen_Configs()
			UpdateWorkerNodes()

	elif command == "cleanworker":
		response = raw_input("Clean and Stop Worker Nodes (y/n)?")
		if response.strip() == "y":
			Check_Master_ETCD_Status()
			Gen_Configs()			
			CleanWorkerNodes()

	elif command == "updatereport":
		response = raw_input_with_default("Deploy IP Reporting Service on Master and ETCD nodes (y/n)?")
		if firstChar(response) == "y":
			Check_Master_ETCD_Status()
			Gen_Configs()
			Update_Reporting_service()


	else:
		printUsage()