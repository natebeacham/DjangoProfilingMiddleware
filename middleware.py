# Orignal version taken from http://www.djangosnippets.org/snippets/186/
# Original author: udfalkso
# Modified by: Shwagroo Team
# Modified again by: natebeacham

import os
import re
import sys
import time
import tempfile
import StringIO
import hotshot, hotshot.stats

from django.conf import settings
		
from django import template
from django.db import connection

DEBUG_TEMPLATE = u'''
<div id="sql">
	<table class="summary">
		<tr><th>Server Time:</th><td>{{ time }}</td></tr>
		<tr><th># of queries:</th><td>{{ count }}</td></tr>
		<tr><th>DB Time:</th><td>{{ db_time }}</td></tr>
	</table>
	
	<div class="queries"">
		{% for query in queries %}
			<table class="query">
				<tr><th>Time:</th><td>{{ query.time }}</td></tr>
				<tr><th>SQL:</th><td>{{ query.sql }}</td></tr>
			</table>
		{% endfor %}
	</div>
</div>
'''

words_re = re.compile( r'\s+' )

group_prefix_re = [
	re.compile( "^.*/django/[^/]+" ),
	re.compile( "^(.*)/[^/]+$" ), # extract module path
	re.compile( ".*" ),		   # catch strange entries
]

class ProfileMiddleware(object):
	"""
	Displays hotshot profiling for any view.
	http://yoursite.com/yourview/?prof

	Add the "prof" key to query string by appending ?prof (or &prof=)
	and you'll see the profiling results in your browser.
	It's set up to only be available in django's debug mode, is available for superuser otherwise,
	but you really shouldn't add this middleware to any production configuration.

	WARNING: It uses hotshot profiler which is not thread safe.
	"""

	def get_debug_context(self, request):
		queries = connection.queries
		db_time = reduce(lambda a, b: (float(a['time']) if isinstance(a, dict) else a) + float(b['time']), connection.queries)

		return {
			'queries': queries,
			'count': len(queries),
			'db_time': db_time, 
			'time': time.time() - self.time_started,
		}

	def process_request(self, request):
		if (settings.DEBUG or request.user.is_superuser) and 'prof' in request.REQUEST:
			self.tmpfile = tempfile.mktemp()
			self.prof = hotshot.Profile(self.tmpfile)
			self.time_started = time.time()

	def process_view(self, request, callback, callback_args, callback_kwargs):
		if (settings.DEBUG or request.user.is_superuser) and 'prof' in request.REQUEST:
			return self.prof.runcall(callback, request, *callback_args, **callback_kwargs)

	def get_group(self, file):
		for g in group_prefix_re:
			name = g.findall( file )
			if name:
				return name[0]

	def get_summary(self, results_dict, sum):
		list = [ (item[1], item[0]) for item in results_dict.items() ]
		list.sort( reverse = True )
		list = list[:40]

		res = "	  tottime\n"
		for item in list:
			res += "%4.1f%% %7.3f %s\n" % ( 100*item[0]/sum if sum else 0, item[0], item[1] )

		return res

	def summary_for_files(self, stats_str):
		stats_str = stats_str.split("\n")[5:]

		mystats = {}
		mygroups = {}

		sum = 0

		for s in stats_str:
			fields = words_re.split(s);
			if len(fields) == 7:
				time = float(fields[2])
				sum += time
				file = fields[6].split(":")[0]

				if not file in mystats:
					mystats[file] = 0
				mystats[file] += time

				group = self.get_group(file)
				if not group in mygroups:
					mygroups[ group ] = 0
				mygroups[ group ] += time

		return "<pre>" + \
			   " ---- By file ----\n\n" + self.get_summary(mystats,sum) + "\n" + \
			   " ---- By group ---\n\n" + self.get_summary(mygroups,sum) + \
			   "</pre>"

	def process_response(self, request, response):
		if (settings.DEBUG or request.user.is_superuser) and 'prof' in request.REQUEST:
			self.prof.close()

			out = StringIO.StringIO()
			old_stdout = sys.stdout
			sys.stdout = out

			stats = hotshot.stats.load(self.tmpfile)
			stats.sort_stats('time', 'calls')
			stats.print_stats()

			sys.stdout = old_stdout
			stats_str = out.getvalue()

			info = self.get_debug_context(request)

			if response and response.content and stats_str:
				info = self.get_debug_context(request)

				response.content = "<pre>" + stats_str + "</pre>" + template.Template(DEBUG_TEMPLATE).render(template.Context(info))

			response.content = "\n".join(response.content.split("\n")[:40])

			response.content += self.summary_for_files(stats_str)

			response.content += template.Template(DEBUG_TEMPLATE).render(template.Context(info))

			os.unlink(self.tmpfile)

		return response