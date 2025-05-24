from mininet.topo import Topo
from mininet.net import Mininet
from mininet.cli import CLI
from mininet.log import setLogLevel

import json
import re
import sys
import subprocess
import os

def launch_mininet_from_json(json_file):
      # Read and parse the JSON file
      with open(json_file, 'r') as f:
            links = json.load(f)
     
      def extract_nodes_from_links(links):
            unique_nodes = set()
            for source, target in links:
                  unique_nodes.add(source)
                  unique_nodes.add(target)
            def node_sort_key(node):
                  match = re.match(r"([a-zA-Z]+)(\d+)", node)
                  if match:
                        prefix, number = match.groups()
                        return (prefix, int(number))
                  return (node, 0)
            return sorted(unique_nodes, key=node_sort_key)

      def run_topo(links, nodes):
            class CustomTopo(Topo):
                  def build(self):
                        # Create nodes
                        for node in nodes:
                              if node.startswith('h'):
                                    self.addHost(node)
                              else:
                                    self.addSwitch(node)
                        # Create links
                        for source, target in links:
                              self.addLink(source, target)

            # Initialize and start the network
            topo = CustomTopo()
            net = Mininet(topo)
            net.start()
            CLI(net)
            net.stop()
      
      # Extract nodes and run topology
      nodes = extract_nodes_from_links(links)
      setLogLevel('info')
      run_topo(links, nodes)

if __name__ == '__main__':
      launch_mininet_from_json(sys.argv[1])
