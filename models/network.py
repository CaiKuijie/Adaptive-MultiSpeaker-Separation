# -*- coding: utf-8 -*-
from utils.ops import scope, AMSGrad, BLSTM, f_props
import os
import config
import tensorflow as tf
import haikunator
from itertools import compress, permutations
import numpy as np
import json
from tensorflow.python.framework import ops

class Network(object):

	"""docstring for Network"""
	def __init__(self, graph=None, *args, **kwargs):		
		# Constant seed for uniform results
		tf.set_random_seed(42)
		np.random.seed(42)

		##
		## Model Configuration 
		if kwargs is not None:
			self.folder = kwargs['type']
			self.S = kwargs['nb_speakers']
			self.args = kwargs
			self.learning_rate = kwargs['learning_rate']
		else:
			raise Exception('Keyword Arguments missing ! Please add the right arguments in input | check doc')

		if graph is None:
			# Run ID
			self.runID = haikunator.Haikunator().haikunate()
			print 'ID : {}'.format(self.runID)

			#Create a graph for this model
			self.graph = tf.Graph()

			with self.graph.as_default():

				with tf.name_scope('inputs'):

					# Boolean placeholder signaling if the model is in learning/training mode
					self.training = tf.placeholder(tf.bool, name='is_training')

					# Batch of raw non-mixed audio
					# shape = [ batch size , number of speakers, samples ] = [ B, S, L]
					self.x_non_mix = tf.placeholder("float", [None, None, None], name='non_mix_input')

					# Batch of raw mixed audio - Input data
					# shape = [ batch size , samples ] = [ B , L ]
					self.x_mix = tf.placeholder("float", [None, None], name='mix_input')

					# Speakers indicies used in the mixtures
					# shape = [ batch size, #speakers]
					self.I = tf.placeholder(tf.int32, [None, None], name='indicies')

					shape_in = tf.shape(self.x_mix)
					self.B = shape_in[0]
					self.L = shape_in[1]

			# Create a session for this model based on the constructed graph
			config_ = tf.ConfigProto()
			config_.gpu_options.allow_growth = True
			config_.allow_soft_placement = True
			self.sess = tf.Session(graph=self.graph, config=config_)

	def tensorboard_init(self):
		with self.graph.as_default():
			self.saver = tf.train.Saver()

			sums = ops.get_collection(ops.GraphKeys.SUMMARIES)
			train_keys_summaries = []
			valid_keys_summaries = []

			for s in sums:
				if not ('input' in s.name or 'output' in s.name):
					train_keys_summaries.append(s)
				else:
					valid_keys_summaries.append(s)
				if 'SDR_improvement' in s.name:
					valid_keys_summaries.append(s)


			self.merged_train = tf.summary.merge(train_keys_summaries)
			if len(valid_keys_summaries) != 0:
 				self.merged_valid = tf.summary.merge(valid_keys_summaries)
 			else:
 				self.merged_valid = None
			self.train_writer = tf.summary.FileWriter(os.path.join(config.log_dir,self.folder,self.runID,'train'), self.graph)
			self.valid_writer = tf.summary.FileWriter(os.path.join(config.log_dir,self.folder,self.runID,'valid'))

			# Save arguments
			with open(os.path.join(config.log_dir,self.folder,self.runID,'params'), 'w') as f:
				json.dump(self.args, f)

	def create_saver(self, subset=None):
		with self.graph.as_default():
			if subset is None:
				self.saver = tf.train.Saver()
			else:
				self.saver = tf.train.Saver(subset)

	# Restore last checkpoint of the current graph using the total path
	# This method is used when we plug a new layer
	def restore_model(self, path):
		with self.graph.as_default():
			tf.train.Saver().restore(self.sess, tf.train.latest_checkpoint(path))
	
	# Restore the last checkpoint of the current trained model
	# This function is maintly used during the test phase
	def restore_last_checkpoint(self):
		self.saver.restore(self.sess, tf.train.latest_checkpoint(os.path.join(config.log_dir, self.folder ,self.runID)))

	def init_all(self):
		with self.graph.as_default():
			self.sess.run(tf.global_variables_initializer())
 
	def non_initialized_variables(self):
		with self.graph.as_default():
			global_vars = tf.global_variables()
			is_not_initialized = self.sess.run([~(tf.is_variable_initialized(var)) \
										   for var in global_vars])
			not_initialized_vars = list(compress(global_vars, is_not_initialized))
			print 'not init: '
			print [v.name for v in not_initialized_vars]
			if len(not_initialized_vars):
				init = tf.variables_initializer(not_initialized_vars)
				return init

	def initialize_non_init(self):
		with self.graph.as_default():
			self.sess.run(self.non_initialized_variables())

	@scope
	def optimize(self):
		print 'Train the following variables :'
		print self.trainable_variables

		optimizer = AMSGrad(self.learning_rate, epsilon=0.001)
		gradients, variables = zip(*optimizer.compute_gradients(self.cost_model, var_list=self.trainable_variables))
		optimize = optimizer.apply_gradients(zip(gradients, variables))
		return optimize

	def save(self, step):
		path = os.path.join(config.log_dir, self.folder ,self.runID, "model")
		self.saver.save(self.sess, path, step)
		return path

	def train(self, X_mix, X_non_mix, I, step):
		summary, _, cost = self.sess.run([self.merged_train, self.optimize, self.cost_model], {self.x_mix: X_mix, self.x_non_mix:X_non_mix, self.training:True, self.I:I})
		self.train_writer.add_summary(summary, step)
		return cost

	def valid_batch(self, X_mix_valid, X_non_mix_valid, I, step):
		if self.merged_valid is None:
			cost = self.sess.run(self.cost_model, {self.x_non_mix:X_non_mix_valid, self.x_mix:X_mix_valid, self.training:False, self.I:I})
		else:
			cost, summary =  self.sess.run([self.cost_model, self.merged_valid], {self.x_non_mix:X_non_mix_valid, self.x_mix:X_mix_valid, self.training:False, self.I:I})
			self.valid_writer.add_summary(summary, step)
		return cost

	def test_batch(self, X_mix_valid, X_non_mix_valid, I):
		return self.sess.run(self.cost_model, {self.x_non_mix:X_non_mix_valid, self.x_mix:X_mix_valid, self.training:False, self.I:I})


	def test(self, X_mix_valid, X_non_mix_valid, I):
		return self.sess.run(self.sepNet.y, {self.x_non_mix:X_non_mix_valid, self.x_mix:X_mix_valid, self.training:False, self.I:I})

	def add_valid_summary(self, val, step):
		summary = tf.Summary()
		summary.value.add(tag="Valid Cost", simple_value=val)
		self.valid_writer.add_summary(summary, step)

	def freeze_all_with(self, prefix):
		to_delete = []
		for var in self.trainable_variables:
			if prefix in var.name:
				to_delete.append(var)
		for to_del in to_delete:
			self.trainable_variables.remove(to_del)

	def freeze_all_except(self, prefix):
		to_train = []
		for var in self.trainable_variables:
			if prefix in var.name:
				to_train.append(var)
		self.trainable_variables = to_train

	@classmethod
	def load(cls, path, modified_args):
		# Load parameters used for the desired model to load
		params_path = os.path.join(path, 'params')
		with open(params_path) as f:
			args = json.load(f)
			keys_to_update = ['learning_rate','epochs','batch_size','regularization','overlap_coef','loss','beta','model_folder']
			to_modify = { key: modified_args[key] for key in keys_to_update if key in modified_args.keys() }
			to_modify.update({key: val for key, val in modified_args.items() if key not in args.keys()})

		# Update with new args such as 'pretraining' or 'type'
		args.update(to_modify)
		# Create a new Adapt model with these parameters
		return cls(**args)

	def finish_construction(self):
		self.trainable_variables = tf.global_variables()


from models.Kmeans_2 import KMeans

class Separator(Network):

	def __init__(self, graph=None, *args, **kwargs):
		super(Separator, self).__init__(graph, *args, **kwargs)

		self.num_speakers = kwargs['tot_speakers']
		self.layer_size = kwargs['layer_size']
		self.embedding_size = kwargs['embedding_size']
		self.normalize = kwargs['no_normalize']
		self.nb_layers = kwargs['nb_layers']
		self.a = kwargs['mask_a']
		self.b = kwargs['mask_b']

		self.plugged = graph is not None
		# If the Separator is not independant but using a front layer
		if self.plugged:
			self.F = kwargs['filters']

			self.graph = graph
			with self.graph.as_default():

				front = self.graph.get_tensor_by_name('front/Reshape_1:0')

				self.B = tf.shape(self.graph.get_tensor_by_name('inputs/non_mix_input:0'))[0]

				with tf.name_scope('split_front'):
					self.X = tf.reshape(front[:self.B, :, :, :], [self.B, -1, self.F]) # Mix input [B, T, N]
					# Non mix input [B, T, N, S]
					self.X_non_mix = tf.transpose(tf.reshape(front[self.B:, :, :, :], [self.B, self.S, -1, self.F]), [0,2,3,1])

				with tf.name_scope('create_masks'):
					# # Batch of Masks (bins label)
					# # shape = [ batch size, T, F, S]
					argmax = tf.argmax(tf.abs(self.X_non_mix), axis=3)
					self.y = tf.one_hot(argmax, self.S, self.a, self.b)
					self.y_test_export = tf.reshape(self.y[:, :, :, 0], [self.B, -1])

				# Speakers indices used in the mixtures
				# shape = [ batch size, #speakers]
				self.I = tf.get_default_graph().get_tensor_by_name('inputs/indicies:0')
		else:
			# STFT hyperparams
			self.window_size = kwargs['window_size']
			self.hop_size = kwargs['hop_size']

			# Network hyperparams
			self.F = kwargs['window_size']//2 +1

	def init_separator(self):
		with self.graph.as_default():
			if self.plugged:
					if self.args['normalize_separator']:
						self.normalization01
					self.prediction
			else:
					self.preprocessing
					if self.args['normalize_separator']:
						self.normalization01
					self.prediction
					#TODO TO IMPROVE ! 
					if 'enhance' not in self.folder:
						self.cost_model = self.cost
						self.finish_construction()
						self.optimize

	def add_enhance_layer(self):
		with self.graph.as_default():
			self.separate
			self.enhance
			self.cost_model = self.enhance_cost
			self.finish_construction()
			self.freeze_all_except('enhance')
			self.optimize

	@scope
	def preprocessing(self):
		self.stfts = tf.contrib.signal.stft(self.x_mix, 
			frame_length=self.window_size, 
			frame_step=self.window_size-self.hop_size,
			fft_length=self.window_size)

		self.B = tf.shape(self.x_non_mix)[0]

		self.stfts_non_mix = tf.contrib.signal.stft(tf.reshape(self.x_non_mix, [self.B*self.S, -1]), 
			frame_length=self.window_size, 
			frame_step=self.window_size-self.hop_size,
			fft_length=self.window_size)

		self.X = tf.sqrt(tf.abs(self.stfts))
		self.X_non_mix = tf.sqrt(tf.abs(self.stfts_non_mix))
		self.X_non_mix = tf.reshape(self.X_non_mix, [self.B, self.S, -1, self.F])
		self.X_non_mix = tf.transpose(self.X_non_mix, [0, 2, 3, 1])

		argmax = tf.argmax(tf.abs(self.X_non_mix), axis=3)
		self.y = tf.one_hot(argmax, self.S, self.a, self.b)

	@scope
	def normalization01(self):
		min_ = tf.reduce_min(self.X, axis=[1,2], keep_dims=True)
		max_ = tf.reduce_max(self.X, axis=[1,2], keep_dims=True)
		self.X = (self.X - min_) / (max_ - min_)

	@scope
	def normalization_mean_std(self):
		mean, var = tf.nn.moments(self.X, axes=[1,2], keep_dims=True)
		self.X = (self.X - mean) / var

	@scope
	def prediction(self):
		pass

	@scope
	def separate(self):
		# Input for KMeans algorithm [B, TF, E]
		input_kmeans = tf.reshape(self.prediction, [self.B, -1, self.embedding_size])
		# S speakers to separate, give self.X in input not to consider silent bins
		kmeans = KMeans(nb_clusters=self.S, nb_iterations=10, input_tensor=input_kmeans, latent_space_tensor=self.X)
		
		# Extract labels of each bins TF_i - labels [B, TF, 1]
		_ , labels = kmeans.network
		self.masks = tf.one_hot(labels, self.S, 1.0, 0.0) # Create masks [B, TF, S]

		separated = tf.reshape(self.X, [self.B, -1, 1])* self.masks # [B ,TF, S] 
		separated = tf.reshape(separated, [self.B, -1, self.F, self.S])
		separated = tf.transpose(separated, [0,3,1,2]) # [B, S, T, F]
		separated = tf.reshape(separated, [self.B*self.S, -1, self.F, 1]) # [BS, T, F, 1]

		return separated
 
	@scope
	def enhance(self):
		# [B, S, T, F]
		separated = tf.reshape(self.separate, [self.B, self.S, -1, self.F])
		if self.args['normalize_enhance']:
			mean, std = tf.nn.moments(separated, axes=[2,3], keep_dims=True)
			print mean
			separated = (separated - mean) / std

		# X [B, T, F]
		# Tiling the input S time - like [ a, b, c] -> [ a, a, b, b, c, c], not [a, b, c, a, b, c]
		X_in = tf.expand_dims(self.X, 1)
		X_in = tf.tile(X_in, [1, self.S, 1, 1])
		X_in = tf.reshape(X_in, [self.B, self.S, -1, self.F])

		# Concat the binary separated input and the actual tiled input
		sep_and_in = tf.concat([separated, X_in], axis = 3)
		sep_and_in = tf.reshape(sep_and_in, [self.B*self.S, -1, 2*self.F])
		
		layers = [
			BLSTM(self.args['layer_size_enhance'], 
				'BLSTM_'+str(i)) for i in range(self.args['nb_layers_enhance'])
		]

		y = f_props(layers, sep_and_in)
		y = tf.layers.dense(y, self.F)

		y = tf.reshape(y, [self.B, self.S, -1]) # [B, S, TF]

		y = tf.transpose(y, [0, 2, 1]) # [B, TF, S]
		if self.args['nonlinearity'] == 'softmax':
			y = tf.nn.softmax(y) * tf.reshape(self.X, [self.B, -1, 1]) # Apply enhanced filters # [B, TF, S] -> [BS, T, F, 1]
		elif self.args['nonlinearity'] == 'tanh':
			y = tf.nn.tanh(y) * tf.reshape(self.X, [self.B, -1, 1]) # Apply enhanced filters # [B, TF, S] -> [BS, T, F, 1]

		# y = y * tf.reshape(self.X, [self.B, -1, 1]) # Apply enhanced filters # [B, TF, S] -> [BS, T, F, 1]
		self.cost_in = y

		y =  tf.transpose(y, [0, 2, 1])
		return tf.reshape(y , [self.B*self.S, -1, self.F, 1])

	@scope
	def enhance_cost(self):
		# Compute all permutations among the enhanced filters [B, TF, S] -> [B, TF, P, S]
		perms = list(permutations(range(self.S))) # ex with 3: [0, 1, 2], [0, 2 ,1], [1, 0, 2], [1, 2, 0], [2, 1, 0], [2, 0, 1]
		length_perm = len(perms)

		# enhance [ B, TF, S] , X [B, T, F] -> [ B, TF, S]
		test_enhance = tf.tile(tf.reshape(tf.transpose(self.cost_in, [0,2,1]), [self.B, 1, self.S, -1]), [1, length_perm, 1, 1]) # [B, S, TF]

		
		perms = tf.reshape(tf.constant(perms), [1, length_perm, self.S, 1])
		perms = tf.tile(perms, [self.B, 1, 1, 1])

		batch_range = tf.tile(tf.reshape(tf.range(self.B, dtype=tf.int32), shape=[self.B, 1, 1, 1]), [1, length_perm, self.S, 1])
		perm_range = tf.tile(tf.reshape(tf.range(length_perm, dtype=tf.int32), shape=[1, length_perm, 1, 1]), [self.B, 1, self.S, 1])
		indicies = tf.concat([batch_range, perm_range, perms], axis=3)

		# [B, P, S, TF]
		permuted_approx= tf.gather_nd(test_enhance, indicies)

		# X_non_mix [B, T, F, S]
		X_non_mix = tf.transpose(tf.reshape(self.X_non_mix, [self.B, 1, -1, self.S]), [0, 1, 3, 2])
		cost = tf.reduce_sum(tf.square(X_non_mix-permuted_approx), axis=-1) # Square difference on each bin 
		cost = tf.reduce_sum(cost, axis=-1) # Sum among all speakers

		cost = tf.reduce_min(cost, axis=-1) # Take the minimum permutation error

		# training_vars = tf.trainable_variables()
		# reg = []
		# for var in training_vars:
		# 	if 'enhance' in var.name:
		# 		reg.append(tf.nn.l2_loss(var))
		# reg = sum(reg)

		cost = tf.reduce_mean(cost) #+ self.adapt_front.l * reg

		# tf.summary.scalar('regularization',  reg)
		tf.summary.scalar('cost', cost)

		return cost