"""
Regression semi-supervised GAN code.
"""
import datetime
import os
import select
import sys

from torch.optim import Adam
import torch

import coefficient_training
import age_training
from settings import Settings, convert_to_settings_list
from training_functions import dnn_training_step, gan_training_step
from utility import SummaryWriter, infinite_iter, clean_scientific_notation, gpu, seed_all

global_trial_directory = None


def run_srgan(settings):
    """
    Train the SRGAN

    :param settings: The settings object.
    :type settings: Settings
    """
    datetime_string = datetime.datetime.now().strftime('y%Ym%md%dh%Hm%Ms%S')
    trial_directory = os.path.join(settings.logs_directory, '{} {}'.format(settings.trial_name, datetime_string))
    global global_trial_directory
    global_trial_directory = trial_directory
    os.makedirs(os.path.join(trial_directory, settings.temporary_directory))
    dnn_summary_writer = SummaryWriter(os.path.join(trial_directory, 'DNN'))
    gan_summary_writer = SummaryWriter(os.path.join(trial_directory, 'GAN'))
    dnn_summary_writer.summary_period = settings.summary_step_period
    gan_summary_writer.summary_period = settings.summary_step_period

    if settings.application == 'coefficient':
        dataset_setup = coefficient_training.dataset_setup
        model_setup = coefficient_training.model_setup
        validation_summaries = coefficient_training.validation_summaries
    elif settings.application == 'age':
        dataset_setup = age_training.dataset_setup
        model_setup = age_training.model_setup
        validation_summaries = age_training.validation_summaries
    else:
        raise ValueError('`application` cannot be {}.'.format(settings.application))

    train_dataset, train_dataset_loader, unlabeled_dataset, unlabeled_dataset_loader, validation_dataset = dataset_setup(
        settings)
    DNN_model, D_model, G_model = model_setup()

    if settings.load_model_path:
        if not torch.cuda.is_available():
            map_location = 'cpu'
        else:
            map_location = None
        DNN_model.load_state_dict(torch.load(os.path.join(settings.load_model_path, 'DNN_model.pth'), map_location))
        D_model.load_state_dict(torch.load(os.path.join(settings.load_model_path, 'D_model.pth'), map_location))
        G_model.load_state_dict(torch.load(os.path.join(settings.load_model_path, 'G_model.pth'), map_location))
    G = gpu(G_model)
    D = gpu(D_model)
    DNN = gpu(DNN_model)
    d_lr = settings.learning_rate
    g_lr = d_lr

    betas = (0.9, 0.999)
    weight_decay = 1e-2
    D_optimizer = Adam(D.parameters(), lr=d_lr, weight_decay=weight_decay)
    G_optimizer = Adam(G.parameters(), lr=g_lr)
    DNN_optimizer = Adam(DNN.parameters(), lr=d_lr, weight_decay=weight_decay)

    step_time_start = datetime.datetime.now()
    print(trial_directory)
    train_dataset_generator = infinite_iter(train_dataset_loader)
    unlabeled_dataset_generator = infinite_iter(unlabeled_dataset_loader)

    for step in range(settings.steps_to_run):
        if step % settings.summary_step_period == 0 and step != 0:
            print('\rStep {}, {}...'.format(step, datetime.datetime.now() - step_time_start), end='')
            step_time_start = datetime.datetime.now()
        # DNN.
        labeled_examples, labels = next(train_dataset_generator)
        dnn_training_step(DNN, DNN_optimizer, dnn_summary_writer, labeled_examples, labels, settings, step)
        # GAN.
        unlabeled_examples, _ = next(unlabeled_dataset_generator)
        gan_training_step(D, D_optimizer, G, G_optimizer, gan_summary_writer, labeled_examples, labels, settings, step,
                          unlabeled_examples)

        if (dnn_summary_writer.step % dnn_summary_writer.summary_period == 0 or
                dnn_summary_writer.step % settings.presentation_step_period == 0):
            validation_summaries(D, DNN, G, dnn_summary_writer, gan_summary_writer, settings, step, train_dataset,
                                 trial_directory, unlabeled_dataset, validation_dataset)
            while sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline()
                if 'save' in line:
                    torch.save(DNN.state_dict(), os.path.join(trial_directory, 'DNN_model_{}.pth'.format(step)))
                    torch.save(D.state_dict(), os.path.join(trial_directory, 'D_model_{}.pth'.format(step)))
                    torch.save(G.state_dict(), os.path.join(trial_directory, 'G_model_{}.pth'.format(step)))
                    print('\rSaved model for step {}...'.format(step))

    print('Completed {}'.format(trial_directory))
    if settings.should_save_models:
        torch.save(DNN.state_dict(), os.path.join(trial_directory, 'DNN_model.pth'))
        torch.save(D.state_dict(), os.path.join(trial_directory, 'D_model.pth'))
        torch.save(G.state_dict(), os.path.join(trial_directory, 'G_model.pth'))


if __name__ == '__main__':
    settings_ = Settings()
    settings_.application = 'age'
    settings_.unlabeled_dataset_size = 1000
    settings_.batch_size = 25
    settings_.summary_step_period = 25
    settings_.labeled_dataset_seed = [0]
    settings_.labeled_dataset_size = [30]
    settings_.unlabeled_loss_multiplier = [1e-1, 1e0, 1e1]
    settings_.fake_loss_multiplier = [1e-1, 1e0, 1e1]
    settings_.steps_to_run = 1000000
    settings_.learning_rate = [1e-5]
    settings_.gradient_penalty_multiplier = [1e-1, 1e0, 1e1, 1e2]
    settings_.norm_loss_multiplier = [0, 0.1]
    settings_.mean_offset = 2
    settings_.unlabeled_loss_order = 2
    settings_.fake_loss_order = [0.5, 1]
    settings_.generator_loss_order = 2
    settings_.generator_training_step_period = 1
    settings_.should_save_models = True
    #settings_.load_model_path = '/home/golmschenk/srgan/logs/detachall ul1e0 fl1e-1 le100 gp1e1 bg1e0 lr1e-5 nl0 gs1 ls0 u2f1g2 l y2018m04d15h14m14s10'
    settings_list = convert_to_settings_list(settings_)
    seed_all(0)
    for settings_ in settings_list:
        trial_name = 'ff3 gpu'
        trial_name += ' ul{:e}'.format(settings_.unlabeled_loss_multiplier)
        trial_name += ' fl{:e}'.format(settings_.fake_loss_multiplier)
        trial_name += ' le{}'.format(settings_.labeled_dataset_size)
        trial_name += ' gp{:e}'.format(settings_.gradient_penalty_multiplier)
        trial_name += ' bg{:e}'.format(settings_.mean_offset)
        trial_name += ' lr{:e}'.format(settings_.learning_rate)
        trial_name += ' nl{}'.format(settings_.norm_loss_multiplier)
        trial_name += ' gs{}'.format(settings_.generator_training_step_period)
        trial_name += ' ls{}'.format(settings_.labeled_dataset_seed)
        trial_name += ' u{}f{}g{}'.format(settings_.unlabeled_loss_order,
                                          settings_.fake_loss_order,
                                          settings_.generator_loss_order)
        trial_name += ' l' if settings_.load_model_path else ''
        settings_.trial_name = clean_scientific_notation(trial_name)
        run_srgan(settings_)
