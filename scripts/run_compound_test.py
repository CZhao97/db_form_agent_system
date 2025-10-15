#!/usr/bin/env python3
import sys
sys.path.append('code')
from compound_tool import CompoundDatabaseTool

print('Running compound tool quick tests')
tool = CompoundDatabaseTool()

print('\n1) Name search: TG(i-16:0/a-17:0/18:0)[rac]')
print(tool._run(compound_name='TG(i-16:0/a-17:0/18:0)[rac]'))

print('\n2) SMILES analysis: CC(=O)OC1=CC=CC=C1C(=O)O')
print(tool._run(smiles='CC(=O)OC1=CC=CC=C1C(=O)O'))

print('\n3) Mass search: 180.16')
print(tool._run(mass=180.16))
