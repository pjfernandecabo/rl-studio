import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import tensorflow as tf
from tqdm import tqdm

from rl_studio.algorithms.ddpg import (
    ModifiedTensorBoard,
    OUActionNoise,
    Buffer,
    DDPGAgent,
)
from rl_studio.envs.gazebo_env import *
from rl_studio.visual.ascii.images import JDEROBOT_LOGO
from rl_studio.visual.ascii.text import JDEROBOT, LETS_GO


def save_stats_episodes(environment, outdir, aggr_ep_rewards, current_time):
    """
    We save info of EPISODES in a dataframe to export or manage
    """

    outdir_episode = f"{outdir}_stats"
    os.makedirs(f"{outdir_episode}", exist_ok=True)

    file_csv = f"{outdir_episode}/{current_time}_Circuit-{environment['circuit_name']}_States-{environment['state_space']}_Actions-{environment['action_space']}_rewards-{environment['reward_function']}.csv"
    file_excel = f"{outdir_episode}/{current_time}_Circuit-{environment['circuit_name']}_States-{environment['state_space']}_Actions-{environment['action_space']}_rewards-{environment['reward_function']}.xlsx"

    df = pd.DataFrame(aggr_ep_rewards)
    df.to_csv(file_csv, mode="a", index=False, header=None)
    df.to_excel(file_excel)


def print_messages(*args, **kwargs):

    print(f"\t------{args[0]}:")
    for key, value in kwargs.items():
        print(f"\t[INFO] {key} = {value}")


class F1TrainerDDPG:
    def __init__(self, params):
        # TODO: Create a pydantic metaclass to simplify the way we extract the params
        # var to config Agents
        self.config = dict(params)

        ## vars to config function main ddpg
        self.agent_name = params.agent["name"]
        self.model_state_name = params.settings["model_state_name"]
        # environment params
        self.outdir = f"{params.settings['output_dir']}{params.algorithm['name']}_{params.agent['name']}_{params.environment['params']['sensor']}"
        self.ep_rewards = []
        self.aggr_ep_rewards = {
            "episode": [],
            "avg": [],
            "max": [],
            "min": [],
            "step": [],
            "epoch_training_time": [],
            "total_training_time": [],
        }
        self.environment_params = params.environment["params"]
        self.env_name = params.environment["params"]["env_name"]
        self.total_episodes = params.settings["total_episodes"]
        self.training_time = params.settings["training_time"]
        self.save_episodes = params.settings["save_episodes"]
        self.save_every_step = params.settings["save_every_step"]
        self.estimated_steps = params.environment["params"]["estimated_steps"]

        # algorithm params
        self.tau = params.algorithm["params"]["tau"]
        self.gamma = params.algorithm["params"]["gamma"]
        self.std_dev = params.algorithm["params"]["std_dev"]
        self.model_name = params.algorithm["params"]["model_name"]
        self.buffer_capacity = params.algorithm["params"]["buffer_capacity"]
        self.batch_size = params.algorithm["params"]["batch_size"]

        # States
        self.state_space = params.agent["params"]["states"]["state_space"]
        self.states = params.agent["params"]["states"]
        # self.x_row = params.agent["params"]["states"][self.state_space][0]

        # Actions
        self.action_space = params.environment["actions_set"]
        self.actions = params.environment["actions"]
        self.actions_size = params.environment["actions_number"]

        # Rewards
        self.reward_function = params.agent["params"]["rewards"]["reward_function"]
        self.highest_reward = params.agent["params"]["rewards"][self.reward_function][
            "highest_reward"
        ]

        # Env
        self.environment = {}
        self.environment["agent"] = params.agent["name"]
        self.environment["model_state_name"] = params.settings["model_state_name"]
        # Env
        self.environment["env"] = params.environment["params"]["env_name"]
        self.environment["training_type"] = params.environment["params"][
            "training_type"
        ]
        self.environment["circuit_name"] = params.environment["params"]["circuit_name"]
        self.environment["launch"] = params.environment["params"]["launch"]
        self.environment["gazebo_start_pose"] = [
            params.environment["params"]["circuit_positions_set"][1][0],
            params.environment["params"]["circuit_positions_set"][1][1],
        ]
        self.environment["alternate_pose"] = params.environment["params"][
            "alternate_pose"
        ]
        self.environment["gazebo_random_start_pose"] = params.environment["params"][
            "circuit_positions_set"
        ]
        self.environment["estimated_steps"] = params.environment["params"][
            "estimated_steps"
        ]
        self.environment["sensor"] = params.environment["params"]["sensor"]
        self.environment["telemetry_mask"] = params.settings["telemetry_mask"]

        # Image
        self.environment["height_image"] = params.agent["params"]["camera_params"][
            "height"
        ]
        self.environment["width_image"] = params.agent["params"]["camera_params"][
            "width"
        ]
        self.environment["center_image"] = params.agent["params"]["camera_params"][
            "center_image"
        ]
        self.environment["image_resizing"] = params.agent["params"]["camera_params"][
            "image_resizing"
        ]
        self.environment["new_image_size"] = params.agent["params"]["camera_params"][
            "new_image_size"
        ]
        self.environment["raw_image"] = params.agent["params"]["camera_params"][
            "raw_image"
        ]
        self.environment["num_regions"] = params.agent["params"]["camera_params"][
            "num_regions"
        ]

        # States
        self.environment["state_space"] = params.agent["params"]["states"][
            "state_space"
        ]
        self.environment["states"] = params.agent["params"]["states"][self.state_space]
        self.environment["x_row"] = params.agent["params"]["states"][self.state_space][
            0
        ]

        # Actions
        self.environment["action_space"] = params.environment["actions_set"]
        self.environment["actions"] = params.environment["actions"]
        self.environment["beta_1"] = -(
            params.environment["actions"]["w_left"]
            / params.environment["actions"]["v_max"]
        )
        self.environment["beta_0"] = -(
            self.environment["beta_1"] * params.environment["actions"]["v_max"]
        )

        # Rewards
        self.environment["reward_function"] = params.agent["params"]["rewards"][
            "reward_function"
        ]
        self.environment["rewards"] = params.agent["params"]["rewards"][
            self.reward_function
        ]
        self.environment["min_reward"] = params.agent["params"]["rewards"][
            self.reward_function
        ]["min_reward"]

        # Algorithm
        self.environment["critic_lr"] = params.algorithm["params"]["critic_lr"]
        self.environment["actor_lr"] = params.algorithm["params"]["actor_lr"]
        self.environment["model_name"] = params.algorithm["params"]["model_name"]

        #
        self.environment["ROS_MASTER_URI"] = params.settings["ros_master_uri"]
        self.environment["GAZEBO_MASTER_URI"] = params.settings["gazebo_master_uri"]
        self.environment["telemetry"] = params.settings["telemetry"]

        print(f"\t[INFO]: environment: {self.environment}\n")

        # Env
        self.env = gym.make(self.env_name, **self.environment)

    def __repr__(self):
        return print(f"\t[INFO]: self.config: {self.config}")

    def main(self):

        random.seed(1)
        np.random.seed(1)
        tf.compat.v1.random.set_random_seed(1)
        print(JDEROBOT)
        print(JDEROBOT_LOGO)

        os.makedirs(f"{self.outdir}", exist_ok=True)

        start_time_training = time.time()
        telemetry_start_time = time.time()
        start_time = datetime.now()
        start_time_format = start_time.strftime("%Y%m%d_%H%M")

        # Reset env
        state, state_size = self.env.reset()

        # Checking state and actions
        print_messages(
            "In RL-Studio main",
            state_size=state_size,
            action_space=self.action_space,
            action_size=self.actions_size,
        )

        ## --------------------- Deep Nets ------------------
        ou_noise = OUActionNoise(
            mean=np.zeros(1), std_deviation=float(self.std_dev) * np.ones(1)
        )
        # Init Agents
        ac_agent = DDPGAgent(
            self.environment, self.actions_size, state_size, self.outdir
        )
        # init Buffer
        buffer = Buffer(
            state_size,
            self.actions_size,
            self.state_space,
            self.action_space,
            self.buffer_capacity,
            self.batch_size,
        )
        # Init TensorBoard
        tensorboard = ModifiedTensorBoard(
            log_dir=f"{self.outdir}/logs_TensorBoard/{self.model_name}-{time.strftime('%Y%m%d-%H%M%S')}"
        )

        ## -------------    START TRAINING --------------------
        print(LETS_GO)
        for episode in tqdm(
            range(self.total_episodes + 1), ascii=True, unit="episodes"
        ):
            tensorboard.step = episode
            done = False
            cumulated_reward = 0
            step = 1
            start_time_epoch = datetime.now()
            prev_state, prev_state_size = self.env.reset()

            # ------- WHILE
            while (
                not done
                and (step < self.estimated_steps)
                and (datetime.now() - timedelta(hours=self.training_time) < start_time)
            ):

                tf_prev_state = tf.expand_dims(tf.convert_to_tensor(prev_state), 0)
                # Get action
                action = ac_agent.policy(tf_prev_state, ou_noise, self.action_space)
                # ic(action)

                state, reward, done, info = self.env.step(action)
                cumulated_reward += reward

                buffer.record((prev_state, action, reward, state))
                buffer.learn(ac_agent, self.gamma)
                ac_agent.update_target(
                    ac_agent.target_actor.variables,
                    ac_agent.actor_model.variables,
                    self.tau,
                )
                ac_agent.update_target(
                    ac_agent.target_critic.variables,
                    ac_agent.critic_model.variables,
                    self.tau,
                )

                prev_state = state
                step += 1

                # save model
                if (
                    step > self.estimated_steps
                    and self.highest_reward < cumulated_reward
                ) or (
                    (datetime.now() - timedelta(hours=self.training_time) > start_time)
                    and self.highest_reward < cumulated_reward
                ):
                    self.highest_reward = cumulated_reward
                    print_messages(
                        "Lap completed in:",
                        time=datetime.now() - start_time_epoch,
                        episode=episode,
                        cumulated_reward=cumulated_reward,
                        total_time=(
                            datetime.now() - timedelta(hours=self.training_time)
                        ),
                    )
                    ac_agent.actor_model.save(
                        f"{self.outdir}/models/{self.model_name}_INTOEPOCH_ACTOR_Max{max_reward}_Avg{average_reward}_Epoch{episode}_EpochTime{start_time_epoch}_inTime{time.strftime('%Y%m%d-%H%M%S')}.model"
                    )
                    ac_agent.critic_model.save(
                        f"{self.outdir}/models/{self.model_name}_INTOEPOCH_CRITIC_Max{max_reward}_Avg{average_reward}_Epoch{episode}_EpochTime{start_time_epoch}_inTime{time.strftime('%Y%m%d-%H%M%S')}.model"
                    )

                # Show stats for debugging
                if not step % self.save_every_step:
                    print_messages(
                        "Showing stats but not saving",
                        episode=episode,
                        cumulated_reward=cumulated_reward,
                        total_time=(datetime.now() - start_time),
                        epoch_time=datetime.now() - start_time_epoch,
                    )

            # WE SAVE BEST VALUES IN EVERY EPISODE
            self.ep_rewards.append(cumulated_reward)
            if not episode % self.save_episodes and episode > 0:
                average_reward = sum(self.ep_rewards[-self.save_episodes :]) / len(
                    self.ep_rewards[-self.save_episodes :]
                )
                min_reward = min(self.ep_rewards[-self.save_episodes :])
                max_reward = max(self.ep_rewards[-self.save_episodes :])
                tensorboard.update_stats(
                    reward_avg=average_reward, reward_max=max_reward, steps=step
                )

                print_messages(
                    "Saving episodes with",
                    episodes=episode,
                    Total_highest_reward=max(self.ep_rewards),
                    max_reward=max_reward,
                    total_time=(datetime.now() - start_time),
                    epoch_time=datetime.now() - start_time_epoch,
                )
                self.aggr_ep_rewards["episode"].append(episode)
                self.aggr_ep_rewards["step"].append(step)
                self.aggr_ep_rewards["avg"].append(average_reward)
                self.aggr_ep_rewards["max"].append(cumulated_reward)
                self.aggr_ep_rewards["min"].append(min_reward)
                self.aggr_ep_rewards["epoch_training_time"].append(
                    (datetime.now() - start_time_epoch).total_seconds()
                )
                self.aggr_ep_rewards["total_training_time"].append(
                    (datetime.now() - start_time).total_seconds()
                )

                if max_reward >= self.highest_reward:
                    tensorboard.update_stats(
                        reward_avg=average_reward, reward_max=max_reward, steps=step
                    )
                    ac_agent.actor_model.save(
                        f"{self.outdir}/models/{self.model_name}_ACTOR_Max{max_reward}_Avg{average_reward}_Epoch{episode}_EpochTime{start_time_epoch}_inTime{time.strftime('%Y%m%d-%H%M%S')}.model"
                    )
                    ac_agent.critic_model.save(
                        f"{self.outdir}/models/{self.model_name}_CRITIC_Max{max_reward}_Avg{average_reward}_Epoch{episode}_EpochTime{start_time_epoch}_inTime{time.strftime('%Y%m%d-%H%M%S')}.model"
                    )
                    save_stats_episodes(
                        self.environment, self.outdir, self.aggr_ep_rewards, start_time
                    )

        save_stats_episodes(
            self.environment, self.outdir, self.aggr_ep_rewards, start_time
        )
        self.env.close()
