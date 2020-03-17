#!/usr/bin/python3
import os
import re
import sys
import time
import utils
import yaml
import argparse
import textwrap
import random
sys.path.append("../utils")
from ConfigUtils import *
from params import default_config_parameters
from cloud_init_deploy import load_node_list_by_role_from_config
from cloud_init_deploy import update_service_path
from cloud_init_deploy import get_kubectl_binary
from cloud_init_deploy import load_config as load_deploy_config
from cloud_init_deploy import render_restfulapi, render_webui, render_storagemanager


FILE_MAP_PATH = 'deploy/cloud-config/file_map.yaml'


def load_config_4_ctl(args, command):
    need_deploy_config = False
    if command in ["svc", "render_template", "download"]:
        need_deploy_config = True
    if not args.config and need_deploy_config:
        args.config = ['config.yaml', 'az_complementary.yaml']
        config = load_deploy_config(args)
        # for configupdate, need extra step to load status.yaml
    else:
        if not args.config and command != "restorefromdir":
            args.config = ['status.yaml']
        config = init_config(default_config_parameters)
        config = add_configs_in_order(args.config, config)
        config["ssh_cert"] = config.get("ssh_cert", "./deploy/sshkey/id_rsa")
    return config


def connect_to_machine(config, args):
    if args.nargs[0] in config['allroles']:
        target_role = args.nargs[0]
        index = int(args.nargs[1])
        nodes, _ = load_node_list_by_role_from_config(config, [target_role])
        node = nodes[index]
    else:
        node = args.nargs[0]
        assert node in config["machines"]
    utils.SSH_connect(config["ssh_cert"], config["machines"][node]
                      ["admin_username"], config["machines"][node]["fqdns"])


def run_kubectl(config, args, commands):
    if not os.path.exists("./deploy/bin/kubectl"):
        print("please make sure ./deploy/bin/kubectl exists. One way is to use ./ctl.py download")
        exit(-1)
    one_command = " ".join(commands)
    nodes, _ = load_node_list_by_role_from_config(config, ["infra"], False)
    master_node = random.choice(nodes)
    kube_command = "./deploy/bin/kubectl --server=https://{}:{} --certificate-authority={} --client-key={} --client-certificate={} {}".format(
        config["machines"][master_node]["fqdns"], config["k8sAPIport"], "./deploy/ssl/ca/ca.pem", "./deploy/ssl/kubelet/apiserver-key.pem", "./deploy/ssl/kubelet/apiserver.pem", one_command)
    output = utils.exec_cmd_local(kube_command, verbose=False)
    if args.verbose:
        print(kube_command)
    print(output)
    return output


def run_script(node, ssh_cert, adm_usr, nargs, sudo=False, noSupressWarning=True):
    if ".py" in nargs[0]:
        if sudo:
            fullcmd = "sudo /opt/bin/python"
        else:
            fullcmd = "/opt/bin/python"
    else:
        if sudo:
            fullcmd = "sudo bash"
        else:
            fullcmd = "bash"
    len_args = len(nargs)
    for i in range(len_args):
        if i == 0:
            fullcmd += " " + os.path.basename(nargs[i])
        else:
            fullcmd += " " + nargs[i]
    srcdir = os.path.dirname(nargs[0])
    utils.SSH_exec_cmd_with_directory(
        ssh_cert, adm_usr, node, srcdir, fullcmd, noSupressWarning)


def run_cmd(node, ssh_cert, adm_usr, nargs, sudo=False, noSupressWarning=True):
    fullcmd = " ".join(nargs)
    utils.SSH_exec_cmd(
        ssh_cert, adm_usr, node, fullcmd, noSupressWarning)


def run_script_wrapper(arg_tuple):
    node, ssh_cert, adm_usr, nargs, sudo, noSupressWarning = arg_tuple
    run_script(node, ssh_cert, adm_usr, nargs, sudo, noSupressWarning)


def run_cmd_wrapper(arg_tuple):
    node, ssh_cert, adm_usr, nargs, sudo, noSupressWarning = arg_tuple
    run_cmd(node, ssh_cert, adm_usr, nargs, sudo, noSupressWarning)


def copy2_wrapper(arg_tuple):
    node, ssh_cert, adm_usr, nargs, sudo, noSupressWarning = arg_tuple
    source, target = nargs[0], nargs[1]
    if sudo:
        utils.sudo_scp(ssh_cert, source, target, adm_usr,
                       node, verbose=noSupressWarning)
    else:
        utils.scp(ssh_cert, source, target, adm_usr,
                  node, verbose=noSupressWarning)


def execute_in_parallel(config, nodes, nargs, sudo, func, noSupressWarning=True):
    args_list = [(config["machines"][node]["fqdns"], config["ssh_cert"],
                  config["admin_username"], nargs, sudo, noSupressWarning) for node in nodes]
    utils.multiprocess_exec(func, args_list, len(nodes))


def get_multiple_machines(config, args):
    valid_roles = set(config['allroles']) & set(args.roles_or_machine)
    valid_machine_names = set(config['machines']) & set(args.roles_or_machine)
    invalid_rom = set(args.roles_or_machine) - \
        valid_roles - valid_machine_names
    if invalid_rom:
        print("Warning: invalid roles/machine names detected, the following names \\\
            are neither valid role names nor machines in our cluster: " + ",".join(list(invalid_rom)))
    nodes, _ = load_node_list_by_role_from_config(config, list(valid_roles), False)
    return nodes + list(valid_machine_names)


def parallel_action_by_role(config, args, func):
    nodes = get_multiple_machines(config, args)
    execute_in_parallel(config, nodes, args.nargs, args.sudo,
                        func, noSupressWarning=args.verbose)


def verify_all_nodes_ready(config, args):
    """
    return unready nodes
    """
    nodes_info_raw = run_kubectl(config, args, ["get nodes"])
    ready_machines = set([entry.split("Ready")[0].strip()
                          for entry in nodes_info_raw.split('\n')[1:]])
    expected_nodes = set(config["machines"].keys())
    nodes_expected_but_not_ready = expected_nodes - ready_machines
    if len(list(nodes_expected_but_not_ready)) > 0:
        print("following nodes not ready:\n{}".format(
            ','.join(list(nodes_expected_but_not_ready))))
        exit(1)


def change_kube_service(config, args, operation, service_list):
    assert operation in [
        "start", "stop"] and "you can only start or stop a service"
    kubectl_action = "create" if operation == "start" else "delete"
    if operation == "start": 
        render_services(config, service_list)
    elif not os.path.exists("./deploy/services"):
        utils.render_template_directory("./services/", "./deploy/services/", config)
    config.pop("machines", [])
    config = add_configs_in_order(["status.yaml"], config)
    service2path = update_service_path()
    for service_name in service_list:
        fname = service2path[service_name]
        dirname = os.path.dirname(fname)
        if os.path.exists(os.path.join(dirname, "launch_order")) and "/" not in service_name:
            with open(os.path.join(dirname, "launch_order"), 'r') as f:
                allservices = f.readlines()
                if operation == "stop":
                    allservices = reversed(allservices)
                for filename in allservices:
                    # If this line is a sleep tag (e.g. SLEEP 10), sleep for given seconds to wait for the previous service to start.
                    if filename.startswith("SLEEP"):
                        if operation == "start":
                            time.sleep(int(filename.split(" ")[1]))
                        else:
                            continue
                    filename = filename.strip('\n')
                    run_kubectl(config, args, [
                                "{} -f {}".format(kubectl_action, os.path.join(dirname, filename))])
        else:
            run_kubectl(config, args, [
                        "{} -f {}".format(kubectl_action, fname)])


def render_services(config, service_list):
    '''render services, ./ctl.py svc render <service name, e.g. monitor>'''
    for svc in service_list:
        if not os.path.exists("./services/{}".format(svc)):
            print("Warning: folder of service {} not found under ./services directory")
            continue
        utils.render_template_directory(
            "./services/{}".format(svc), "./deploy/services/{}".format(svc), config)


def remote_config_update(config, args):
    '''
    client end(infra/NFS node) config file update
    ./ctl.py -s svc configupdate restful_api
    ./ctl.py [-r storage_machine1 [-r storage_machine2]] -s svc configupdate storage_manager
    '''
    assert args.nargs[1] in ["restful_api", "storage_manager",
                             "dashboard"] and "only support updating config file of restfulapi and storagemanager"
    # need to get node list for this subcommand of svc, so load status.yaml
    if not os.path.exists(FILE_MAP_PATH):
        utils.render_template("template/cloud-config/file_map.yaml", FILE_MAP_PATH, config)
    with open(FILE_MAP_PATH) as f:
        file_map = yaml.load(f)
    if args.nargs[1] in ["restful_api", "dashboard"]:
        render_func = {"restful_api": render_restfulapi,
                       "dashboard": render_webui}
        render_func[args.nargs[1]](config)
        # pop out the machine list in az_complementary.yaml, which describe action instead of status
        config.pop("machines", [])
        config = add_configs_in_order(["status.yaml"], config)
        infra_nodes, _ = load_node_list_by_role_from_config(config, ["infra"], False)
        src_dst_list = [file_map[args.nargs[1]][0]
                        ["src"], file_map[args.nargs[1]][0]["dst"]]
        execute_in_parallel(config, infra_nodes, src_dst_list,
                            args.sudo, copy2_wrapper, noSupressWarning=args.verbose)
    elif args.nargs[1] == "storage_manager":
        config.pop("machines", [])
        config = add_configs_in_order(["status.yaml"], config)
        nfs_nodes, _ = load_node_list_by_role_from_config(config, ["nfs"], False)
        if args.roles_or_machine == ['nfs'] or not args.roles_or_machine:
            nodes_2_update = nfs_nodes
        else:
            nodes_2_update = list(set(nfs_nodes) & set(args.roles_or_machine))
        for node in nodes_2_update:
            render_storagemanager(config, node)
            src_dst_list = ["./deploy/StorageManager/{}_storage_manager.yaml".format(
                node), "/etc/StorageManager/config.yaml"]
            args_list = (config["machines"][node]["fqdns"], config["ssh_cert"],
                         config["admin_username"], src_dst_list, args.sudo, args.verbose)
            copy2_wrapper(args_list)


def render_template_or_dir(config, args):
    nargs = args.nargs
    # no destination, then mirror one in ./deploy folder
    src = nargs[0]
    if len(nargs) == 1:
        dst = os.path.join("deploy", src.split("template/")[1])
    else:
        dst = nargs[1]
    if os.path.isdir(src):
        utils.render_template_directory(src, dst, config)
    else:
        utils.render_template(src, dst, config)


def run_command(args, command):
    config = load_config_4_ctl(args, command)
    if command == "restorefromdir":
        utils.restore_keys_from_dir(args.nargs)
    if command == "connect":
        connect_to_machine(config, args)
    if command == "kubectl":
        run_kubectl(config, args, args.nargs[0:])
    if command == "runscript":
        parallel_action_by_role(config, args, run_script_wrapper)
    if command == "runcmd":
        parallel_action_by_role(config, args, run_cmd_wrapper)
    if command == "copy2":
        parallel_action_by_role(config, args, copy2_wrapper)
    if command == "backuptodir":
        utils.backup_keys_to_dir(args.nargs)
    if command == "restorefromdir":
        utils.restore_keys_from_dir(args.nargs)
    if command == "verifyallnodes":
        verify_all_nodes_ready(config, args)
    if command == "svc":
        assert len(
            args.nargs) > 1 and "at least 1 action and 1 kubernetes service name should be provided"
        if args.nargs[0] == "start":
            change_kube_service(config, args, "start", args.nargs[1:])
        elif args.nargs[0] == "stop":
            change_kube_service(config, args, "stop", args.nargs[1:])
        elif args.nargs[0] == "render":
            render_services(config, args.nargs[1:])
        elif args.nargs[0] == "configupdate":
            remote_config_update(config, args)
    if command == "render_template":
        render_template_or_dir(config, args)
    if command == "download":
        if not os.path.exists('deploy/bin/kubectl') or args.force:
            get_kubectl_binary(config)


if __name__ == '__main__':
    # the program always run at the current directory.
    # ssh -q -o "StrictHostKeyChecking no" -o "UserKnownHostsFile=/dev/null" -i deploy/sshkey/id_rsa core@
    dirpath = os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
    os.chdir(dirpath)
    parser = argparse.ArgumentParser(prog='maintain.py',
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     description=textwrap.dedent('''
        Maintain the status of the cluster.

        Prerequest:
        * Have the accumulated config file ready.

        Command:
            connect  connect to a machine in the deployed cluster
    '''))
    parser.add_argument('-cnf', '--config', action='append', default=[], help='Specify the config files you want to load, later ones \
        would overwrite former ones, e.g., -cnf config.yaml -cnf az_complementary.yaml')
    parser.add_argument('-i', '--in', action='append',
                        default=[], help='Files to take as input')
    parser.add_argument('-o', '--out', help='File to dump to as output')
    parser.add_argument("-v", "--verbose",
                        help="verbose print", action="store_true")
    parser.add_argument('-r', '--roles_or_machine', action='append', default=[], help='Specify the roles of machines that you want to copy file \
        to or execute command on')
    parser.add_argument("-s", "--sudo", action="store_true",
                        help='Execute scripts in sudo')
    parser.add_argument("-f", "--force", action="store_true",
                        help='Force execution')
    parser.add_argument("command",
                        help="See above for the list of valid command")
    parser.add_argument('nargs', nargs=argparse.REMAINDER,
                        help="Additional command argument")
    args = parser.parse_args()
    command = args.command
    nargs = args.nargs

    run_command(args, command)