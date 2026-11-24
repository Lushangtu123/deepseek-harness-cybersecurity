"""Exercise the exact guest controller embedded in the installed manager."""
import ast
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


class CapabilityTransition(unittest.TestCase):
 def load(self):
  manager=Path(__file__).with_name('manage.py')
  tree=ast.parse(manager.read_text())
  source=next(ast.literal_eval(node.value) for node in tree.body
   if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='CAPABILITIES_GUEST_SCRIPT' for target in node.targets))
  namespace={'__name__':'capability_transition_fixture'}
  exec(compile(source,str(manager)+':guest-controller','exec'),namespace)
  return SimpleNamespace(**namespace)

 def test_switch_success_is_observed_after_restart(self):
  module=self.load()
  with tempfile.TemporaryDirectory() as directory:
   state=Path(directory)/'mode';state.write_text('off\n');calls=[]
   result=module.transition(state,True,lambda:calls.append('restart'),lambda expected:True)
   self.assertTrue(result);self.assertEqual(state.read_text(),'on\n');self.assertEqual(calls,['restart'])

 def test_failed_enable_restores_previous_state_and_restarts_it(self):
  module=self.load()
  with tempfile.TemporaryDirectory() as directory:
   state=Path(directory)/'mode';state.write_text('off\n');calls=[]
   def restart():calls.append(state.read_text().strip())
   with self.assertRaisesRegex(RuntimeError,'not confirmed'):
    module.transition(state,True,restart,lambda expected:not expected)
   self.assertEqual(state.read_text(),'off\n');self.assertEqual(calls,['on','off'])

 def test_corrupt_or_link_state_is_not_silently_replaced(self):
  module=self.load()
  with tempfile.TemporaryDirectory() as directory:
   state=Path(directory)/'mode';state.write_text('garbage\n')
   with self.assertRaises(ValueError):module.read_mode(state)
   other=Path(directory)/'linked';other.symlink_to(state)
   with self.assertRaises(ValueError):module.read_mode(other)

 def test_disabled_default_does_not_create_a_mode_file(self):
  module=self.load()
  with tempfile.TemporaryDirectory() as directory:
   state=Path(directory)/'mode'
   self.assertFalse(module.read_mode(state));self.assertFalse(state.exists())

 def test_readiness_requires_authenticated_plugin_acknowledgement(self):
  module=self.load()
  good={'ok':True,'ready':True,'originalCapabilities':{'enabled':True,'managed':True}}
  self.assertTrue(module.confirmed_plugin_mode(200,good,True))
  self.assertFalse(module.confirmed_plugin_mode(401,good,True))
  self.assertFalse(module.confirmed_plugin_mode(200,good,False))
  self.assertFalse(module.confirmed_plugin_mode(200,{'ok':True,'ready':True},True))


if __name__=='__main__':unittest.main()
