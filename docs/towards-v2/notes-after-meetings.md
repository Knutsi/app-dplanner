# Notes after the conference — towards v2

*Voice memo dictated after the conference. Names of people and places are removed; background announcements picked up by the recording are cut. Parts (a) and (b) are a reading of the memo. Part (c) is what was said. Remarks marked "Added later" are not from the memo.*

## The thesis in one paragraph

DPlanner works well today for one developer on one project. The conference pointed to a bigger version: a **production floor** (not a "lights-out" factory with no people in it). **Systems** hold lasting knowledge about the product and its domain. **Workers** (people, and automated workers running as daemons) claim parts of a plan through a small **real-time multiplayer layer**. Each piece of work runs through a planned **chain of agents** that includes adversarial review. **Reporting** lets non-experts see what is being built and what it costs. The step graph we already have is the core of all of this, not something to replace.

## (a) Ideas at a glance

**Knowledge: what the planner knows beyond one project**
1. **A system level above projects**: Projects are grouped under *systems* that hold domain knowledge, architecture and lessons from past projects.
2. **The factory door**: You chat with a system to brainstorm or order work based on specs, and its knowledge plus your team's experts turn the request into a plan. 
3. **A knowledge graph behind the system**: RAG and vector search could build a knowledge graph out of a system's documents and history. Its value is not yet proven.

**Execution: how the plan gets carried out**
4. **A production floor, not lights-out**: Full autonomy is out of reach, so the explicit step graph is worth keeping even when agents do the work.
5. **An autonomous worker (a daemon)**: An automated worker, running as a daemon, claims a region of the plan and carries it out.
6. **A multiplayer server**: A small real-time backend next to git shows who (person or agent) is working where, and carries messages between them.
7. **Multi-agent work chains ("playbooks")**: A step's work is a pre-planned chain of agents, for example implement → commit → adversarial review by another vendor's model.
8. **Explore autonomy, hand-back and budget**: Study how agents run on their own, send work back and forth, and are budgeted, starting with the presenter's project.

**Visibility: who can see and steer the floor**
9. **Tools for product owners**: People who are not software experts can start work, look at what is happening and see what changes cost in compute, from a total overview that takes resource planning into account.
10. **Reporting: a production and change service**: Reports across a whole plan repository, at system and project level.
11. **Showing artifacts on the floor**: Things the work produces are shown to the people involved, inside the plan.
12. **An enterprise software layer (far horizon)**: The same machinery could serve a whole business, for example by watching markets, prices and public tenders.

**How the ideas depend on each other:** 2 needs 1, and 3 is one way to power both. 5 needs 6, because claiming work only makes sense if others can see the claim. 7 is what a worker (5) runs, and 8 is the research behind 5 to 7. 9 to 11 are three views of one surface.

## (b) The ideas in detail

### Knowledge

#### 1. A system level above projects
- **What:** A level above projects, in addition to Library → Project → Step. A system groups projects and holds domain documentation, architecture and application-level documentation, and experience from issues that came up during development.
- **Why:** The planner is missing "systematic information about the product and the architecture of the product that crosses projects". Each project ends, but the knowledge it produced should last. The old idea of a system level "is now becoming more and more meaningful".
- **Open questions:** Is a system a new kind of node, or a folder that holds projects? Where does its knowledge live on disk (see `FORMAT.md`)? How do lessons from a finished project get collected into its system?

#### 2. The factory door: talk to the system
- **What:** A chat with the system. You "order" something, and specialists use what the system knows about the domain and earlier projects to propose how to build it. They also take input from the experts on your own team: architecture, system design, UX, and domain experts such as clinicians, technicians and equipment vendors.
- **Why:** You use the system for more than planning one project. You also think through problems against everything it knows ("intriguing and interesting").
- **Open questions:** What does the chat produce: a draft project, steps, or only answers? How does a human expert's input get recorded so it lasts?

#### 3. A knowledge graph behind the system
- **What:** RAG and vector-database methods (shown by [a consultant]) that build a knowledge graph over a project's material.
- **Why:** It is a likely engine for 1 and 2.
- **Open questions:** The memo says only "valuable, perhaps". What would it answer that plain documents and search cannot?

### Execution

#### 4. A production floor, not lights-out
- **What:** There are two models. In the *lights-out* factory, software is built with no people involved. In the *human-in-the-loop* project, people take a large part. The memo bets on a mix: a production floor that people walk onto and work on.
- **Why:** Lights-out "seems unlikely at the current state of affairs". Testing, iteration and testing with customers will always need people. So "the planner setup as it is today is actually super valuable also in an autonomous setting".
- **Caution (memo's own):** "Be a bit cautious with these analogies. They trap your thinking." *Factory* and *floor* are just figures of speech, not designs.

#### 5. An autonomous worker (a daemon)
- **What:** A worker that operates on DPlanner and carries out a project, claiming specific parts of the tree. Automated workers are **daemons**: long-running background processes that need no window open, pick up claimable work on their own, and report through the multiplayer server (6).
- **Why:** This is the missing piece between a plan and autonomous execution.
- **Open questions:** What can be claimed: a step, a branch of the graph, a path? How is a claim released when a worker stalls?

#### 6. A multiplayer server
- **What:** The data stays where it is now, with the plan and the code in git. On top sits a "tiny backend" for real-time communication that:
  - runs autonomous work (5) and lets it take charge of regions of the plan;
  - shows people working by hand which nodes, paths and branches their colleagues are on, so two people don't do the same work;
  - carries conversation about the plan between users, and possibly between the agents they started.
- **Why:** Claiming work, avoiding collisions and talking about the plan all need shared live state, and git alone does not provide that.
- **Open questions:** What state lives only on the server, and what gets written back to git? (Rule today: derived facts are never stored, and every change goes through a command.)

#### 7. Multi-agent work chains ("playbooks")
- **What:** Today an agent step means roughly: start an agent, get a PR, review it or commit it. The next stage is a *flow* of agents for one task. An implementing agent and a reviewer draw on each other, or call subagents from other vendors with particular skills loaded, to check the work more thoroughly at a higher cost. The chain is planned in advance, for example *commit straight to the branch* → *adversarial review with another provider's model*. Agents may load extra domain skills as they go, but the system itself must start the reviewer and carry messages between the agents.
- **Why:** "Wisely applying them throughout the task chain and the task dependency tree" is "probably very, very wise". Different steps deserve different amounts of care and cost.
- **Name (the memo asked for one). Added later:** **playbook**. It means a named, reusable chain of *stages*, each stage being one agent with one model, harness and skill set plus a rule for passing work on (commit, PR, review, send back). "This step runs the *Careful change* playbook" reads naturally. *Agent profile* keeps its current meaning: the settings for one stage. Other names considered: *pipeline* (sounds like CI), *recipe*, *workflow* (already used by tooling), *crew* (names the agents, not the order).
- **Added later:** This builds on what exists. Agent profiles, harnesses and the *Review rounds* aspect are already partial versions of these stages.

#### 8. Explore autonomy, hand-back and budget
- **What:** Research how agents can run autonomously, how they best communicate "when you bounce something back", and how to budget for that.
- **Next action:** Look at the presenter's project for lessons.

### Visibility

#### 9. Tools for product owners
- **What:** Product-owner tools for working with the factory are maturing.
- **Why:** It makes the work open to inspection, and it lets people who are not software experts start tasks and see the cost in compute of changing the product.
- **Must include:**
  - **A total overview:** one view across all systems and projects, not one project at a time.
  - **Resource planning:** the people and the compute (daemons, agent runs, budget) that are available, set against the work that is planned, so a product owner can see what fits and what doesn't.
- **Open questions:** Is resource planning a new derivation over the existing estimates and schedule (`domain/schedule.py`), or a new kind of data? How is a daemon's capacity counted next to a person's?

#### 10. Reporting: a production and change service
- **What:** A front end and back end (or some other mechanism) that reports on a whole plan repository, at both system and project level.
- **Why:** So that "people understand what is going on in the production area". In short, DPlanner as a *production and change service*.
- **Added later:** This is a larger version of today's report command, which works on one project at a time.

#### 11. Showing artifacts on the floor
- **What:** A way to show the artifacts the work produces to the people involved, inside the plan.
- **Why:** "There will be questions arising." People answer them better when they can see what was actually made.

#### 12. An enterprise software layer (far horizon)
- **What:** The same machinery as a software layer for a whole business, holding the skills that business needs, including autonomous monitoring of markets, prices and public tenders.
- **Status:** Only a direction. Nothing to build yet.

## (c) Transcript (names and places removed)

Some thoughts on the AI, cool presentations that we had yesterday on the conference. The planner, as it sits right now, works best if you're an individual developer, and it has cool aspects in its planning.

It's missing systematic information about the product and the architecture of the product that crosses projects. The original idea of having a system level to the program is now becoming more and more meaningful, and the system could also cover documentation and experiences in the domain, and longer-term experiences with issues that arise during development. So this documentation level on the domain and the pro- and the application level is something that we should work on implementing. It means that projects will be gathered under systems. And systems have domain and architectural information and experiences from past projects. So, we need to think a little bit about how to build that into the product.

The next thing is the idea of a more friendly… Oh, one miss. The more free mechanism to you. To instruct you. You will create the system level novel. *[unclear]* *[background announcement removed]* Sorry, there was some announcement on the speakers here. I can keep that in mind when you parse the transcript.

Okay, so the next challenge we're looking at here is… So one thing that was interesting about [a presenter]'s presentation is the idea that you can brainstorm and query the, or basically have a chat with the system. So it's like a factory door, and you order something from the factory, and then multiple sort of specialists, or the system, will use the knowledge that it has about the domain, previous projects and so on, and come up with a plan for how to build it. And the system will also take inputs from various experts that are on your teams. The example of an expert here is architecture, system-level design and UX experts, also domain experts, such as clinicians, technicians, equipment vendors, and so on. So the ability to interact with the system beyond just planning a project, but also to brainstorm with the knowledge that exists in this system, is intriguing and interesting.

Another aspect that [a consultant] was showing us was, of course, the RAG and vector database mechanisms that he had demonstrated, to create a knowledge graph for himself in his project. This knowledge graph is valuable, perhaps.

The next step is the lights-out autonomy mechanism. It feels like there are two different paradigms emerging here. One paradigm is the lights-out, and the other one is the project with manual intervention, or a major human-in-the-loop component. It seems unlikely at the current state of affairs that the lights-out software factory is achievable. There will be at least human elements, and some projects will always have a human element for testing and iteration and testing with customers and so on, that a lights-out factory would never be able to produce. Because of this, it might be that the planner setup as it is today is actually super valuable also in an autonomous setting. What we are missing here is a worker that can operate on the DPlanner and execute the project — an automated worker.

The automated worker also nicely connects to the next concept, which is the multiplayer idea: that you have a server, you maintain your data in the git repository, you maintain your plan and the code repository structure, but in addition to this, you have a real-time communication layer that basically is a tiny front end — no, sorry, tiny backend — that helps, that can execute work autonomously and take charge of specific regions. And this multiplayer server would also allow users, human users, when they are manually working through the work plan, to communicate in real time with their colleagues what nodes, what paths, what branches they're operating on, so that there is no collision, and the same people do not do work on the same part of the project plan or project tree. It should also facilitate communication about the plan between the users, and potentially between the agents that the users have started on various parts of the plan.

And then there's that next layer, which is multi-agent tasks. What I'm thinking here is that there are sort of agent processes as well. So a step is not necessarily automatically an agent step. You think about this as, you know, just firing up a terminal, producing a PR and then having that reviewed, or committing that to a branch. The next evolution in agent profiles is to go and say, well, one thing is *[unclear]*, but the other thing you could do is you can put a flow of multiple agents that interact with your solution *[unclear]*. So you have the implementing agent and the review agent. And they can draw on each other's expertise, or draw on subagents from other vendors with specific skills loaded, to quality assure, at a higher cost, a particular task. So once a step is done, the profile, for instance, could say that this step commits directly to the branch. And then the next job profile is: at this point you will run through an antagonistic review with a model from this other provider. So part of the work of this factory concept is to set up these work profiles, or work… Missing a good word for this. So, agent, please think about a good terminology for this one. So when you have a piece of work, you should be able to set up a chain of specific skills, pre-planned. They can load the skills as they want them from the domain, perhaps, but we do want the system to be able to launch another agent for antagonistic review, and communicate with them. *[background announcement removed]*

Okay, so one more additional note here. There is also this maturation of the tools related to product owners and how they will interact with this sort of factory idea. And this factory idea is probably really, really wise, because it will allow a degree of inspection, but it also allows non-experts on the software domain to come in and operate on the factory, to initiate tasks and understand the budgeting and costs in terms of compute that goes into modifying the product.

Okay, so two additional points to add here. One is a [front end] we need. So we talked about the worker instance, but we do also need reporting. So we need a front-end and backend mechanism, or some mechanism of reporting, that's able to report on an entire plan repository and report both on the system and project levels, so people understand what is going on in the production area. So you can think about this as a production service. Production and change service. This might in the future also conceptually be extended to being a software layer for the enterprise that has the specialized skills that that specific enterprise needs, including autonomous surveillance of markets and prices and public [tenders] and so on. This is totally true. *[background announcement removed]*

Okay, so I think we're looking at an autonomous worker that can claim specific parts of the tree. This has to then include a real-time multiplayer service, and we have to have a friendly human interface for this sort of production-floor concept. So, a little bit contrasting the idea of a lights-out software factory, I think we're looking at a production-floor-style mechanism where you will go and interact.

And there will be questions arising, and that's the last point. Do we need to have a way to show artifacts to the people involved, as part of the work process on the floor, on the plan?

Also, note to self: be a bit cautious with these analogies. They trap your thinking. But antagonistic review and the multi-agent work profiles for specific tasks, and wisely applying them throughout the task chain and the task dependency tree — probably very, very wise. So an exploration also is due on the various agents and how you can operate them autonomously, and best communicate between them when you bounce something back, and how to budget that. Might be an idea to look at [a presenter]'s project to see how he has done it, and is there any lessons to draw from that? Thank you.
