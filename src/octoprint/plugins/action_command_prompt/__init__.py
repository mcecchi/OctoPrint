# coding=utf-8
from __future__ import absolute_import, division, print_function, unicode_literals

__license__ = 'GNU Affero General Public License http://www.gnu.org/licenses/agpl.html'
__copyright__ = "Copyright (C) 2018 The OctoPrint Project - Released under terms of the AGPLv3 License"

import octoprint.plugin

from octoprint.server import user_permission

import flask
from flask_babel import gettext

class Prompt(object):

	def __init__(self, text):
		self.text = text
		self.choices = []

		self._active = False

	@property
	def active(self):
		return self._active

	def add_choice(self, text):
		self.choices.append(text)

	def activate(self):
		self._active = True

	def validate_choice(self, choice):
		return 0 <= choice < len(self.choices)


class ActionCommandPromptPlugin(octoprint.plugin.AssetPlugin,
                                octoprint.plugin.SettingsPlugin,
                                octoprint.plugin.SimpleApiPlugin,
                                octoprint.plugin.TemplatePlugin):

	COMMAND = "M876"

	# noinspection PyMissingConstructor
	def __init__(self):
		self._prompt = None
		self._command = None
		self._enable_emergency_sending = False

	def initialize(self):
		self._command = self._settings.get([b"command"])
		self._enable_emergency_sending = self._settings.get_boolean([b"enable_emergency_sending"])

	#~ AssetPlugin

	def get_assets(self):
		return dict(js=["js/action_command_prompt.js"],
		            clientjs=["clientjs/action_command_prompt.js"])

	#~ SettingsPlugin

	def get_settings_defaults(self):
		return dict(command=self.COMMAND,

		            # TODO make this default to True once we have a capability report to listen to
		            enable_emergency_sending=False)

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
		self._command = self._settings.get([b"command"])
		self._enable_emergency_sending = self._settings.get_boolean([b"enable_emergency_sending"])

	#~ SimpleApiPlugin

	def get_api_commands(self):
		return dict(select=["choice"])

	def on_api_command(self, command, data):
		if command == "select":
			if not user_permission.can():
				return flask.abort(403, "Insufficient permissions")

			if self._prompt is None:
				return flask.abort(409, "No active prompt")

			choice = data["choice"]
			if not isinstance(choice, int) or not self._prompt.validate_choice(choice):
				return flask.abort(400, "{!r} is not a valid value for choice".format(choice))

			self._answer_prompt(choice)

	def on_api_get(self, request):
		if not user_permission.can():
			return flask.abort(403, "Insufficient permissions")
		if self._prompt is None:
			return flask.jsonify()
		else:
			return flask.jsonify(text=self._prompt.text, choices=self._prompt.choices)

	#~ TemplatePlugin

	def get_template_configs(self):
		return [dict(type="settings", name=gettext("Action Command Prompt"), custom_bindings=False)]

	#~ action command handler

	def action_command_handler(self, comm, line, action, *args, **kwargs):
		if not action.startswith(b"prompt_"):
			return

		parts = action.split(None, 1)
		if len(parts) == 1:
			action = parts[0]
			parameter = b""
		else:
			action, parameter = parts

		if action == b"prompt_begin":
			if self._prompt is not None and self._prompt.active:
				self._logger.warn("Prompt is already defined")
				return
			self._prompt = Prompt(parameter.strip())

		elif action == b"prompt_choice" or action == b"prompt_button":
			if self._prompt is None:
				return
			if self._prompt.active:
				self._logger.warn("Prompt is already active")
				return
			self._prompt.add_choice(parameter.strip())

		elif action == b"prompt_show":
			if self._prompt is None:
				return
			if self._prompt.active:
				self._logger.warn("Prompt is already active")
				return
			self._show_prompt()

		elif action == b"prompt_end":
			if self._prompt is None:
				return
			self._close_prompt()
			self._prompt = None

	#~ queuing handling

	def gcode_queuing_handler(self, comm_instance, phase, cmd, cmd_type, gcode, subcode=None, tags=None, *args, **kwargs):
		if gcode != self._command:
			return

		if not self._enable_emergency_sending:
			return

		if not "S" in cmd:
			# we only force-send M876 Sx
			return

		# noinspection PyProtectedMember
		return comm_instance._emergency_force_send(cmd, u"Force-sending {} to the printer".format(self._command), gcode=gcode)

	#~ prompt handling

	def _show_prompt(self):
		self._prompt.activate()
		self._plugin_manager.send_plugin_message(self._identifier, dict(action="show",
		                                                                text=self._prompt.text,
		                                                                choices=self._prompt.choices))

	def _close_prompt(self):
		self._prompt = None
		self._plugin_manager.send_plugin_message(self._identifier, dict(action="close"))

	def _answer_prompt(self, choice):
		self._close_prompt()
		self._printer.commands(["{command} S{choice}".format(command=self._command,
		                                                     choice=choice)])


__plugin_name__ = "Action Command Prompt Support"
__plugin_description__ = "Allows your printer to trigger prompts via action commands on the connection"
__plugin_author__ = "Gina Häußge"
__plugin_disabling_discouraged__ = gettext("Without this plugin your printer will no longer be able to trigger"
                                           "confirmation or selection prompts in OctoPrint")
__plugin_license__ = "AGPLv3"
__plugin_implementation__ = ActionCommandPromptPlugin()
__plugin_hooks__ = {
	b"octoprint.comm.protocol.action": __plugin_implementation__.action_command_handler,
	b"octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.gcode_queuing_handler
}
