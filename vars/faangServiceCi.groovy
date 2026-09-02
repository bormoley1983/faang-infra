def call(Map configuration = [:]) {
    List<String> integrationTasks = (configuration.integrationTasks ?: []) as List<String>
    List<String> integrationDependencies = (configuration.integrationDependencies ?: []) as List<String>
    Set<String> dependencySet = integrationDependencies as Set
    Set<String> supportedDependencies = ['postgres', 'redis', 'kafka'] as Set
    Set<String> unsupportedDependencies = dependencySet.findAll {
        String dependency -> !supportedDependencies.contains(dependency)
    } as Set

    if (!unsupportedDependencies.isEmpty()) {
        error("Unsupported integration dependencies: ${unsupportedDependencies.sort().join(', ')}")
    }
    if (!dependencySet.isEmpty() && integrationTasks.isEmpty()) {
        error('Integration dependencies require at least one integration task')
    }

    List<String> verificationTasks = ['clean', 'build'] + integrationTasks
    String taskArguments = verificationTasks.collect { String task ->
        if (!(task ==~ /[A-Za-z][A-Za-z0-9_-]*/)) {
            error("Invalid Gradle task name: ${task}")
        }
        task
    }.join(' ')

    String integrationEnvironment = dependencySet.isEmpty() ? '' : '''
        - name: FAANG_CI_INTEGRATION
          value: "true"'''
    if (dependencySet.contains('postgres')) {
        integrationEnvironment += '''
        - name: FAANG_TEST_POSTGRES_URL
          value: jdbc:postgresql://localhost:5432/ci_test
        - name: FAANG_TEST_POSTGRES_USER
          value: ci_test
        - name: FAANG_TEST_POSTGRES_PASSWORD
          value: ""'''
    }
    if (dependencySet.contains('redis')) {
        integrationEnvironment += '''
        - name: FAANG_TEST_REDIS_HOST
          value: localhost
        - name: FAANG_TEST_REDIS_PORT
          value: "6379"'''
    }
    if (dependencySet.contains('kafka')) {
        integrationEnvironment += '''
        - name: FAANG_TEST_KAFKA_BOOTSTRAP
          value: localhost:9092'''
    }

    String dependencyContainers = ''
    String dependencyVolumes = ''
    if (dependencySet.contains('postgres')) {
        dependencyContainers += '''
    - name: postgres
      image: postgres:18-alpine@sha256:d3e1620b530c944afa6e887d22eb899824da68e19c52024bf98f5220c88a65b2
      imagePullPolicy: IfNotPresent
      env:
        - name: POSTGRES_DB
          value: ci_test
        - name: POSTGRES_USER
          value: ci_test
        - name: POSTGRES_HOST_AUTH_METHOD
          value: trust
        - name: PGDATA
          value: /var/lib/postgresql/data
      resources:
        requests:
          cpu: 100m
          memory: 192Mi
        limits:
          cpu: "1"
          memory: 768Mi
      securityContext:
        allowPrivilegeEscalation: false
        runAsNonRoot: true
        runAsUser: 70
        runAsGroup: 1000
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: postgres-data
          mountPath: /var/lib/postgresql
        - name: postgres-run
          mountPath: /var/run/postgresql
        - name: postgres-tmp
          mountPath: /tmp
'''
        dependencyVolumes += '''
    - name: postgres-data
      emptyDir:
        sizeLimit: 1Gi
    - name: postgres-run
      emptyDir:
        sizeLimit: 16Mi
    - name: postgres-tmp
      emptyDir:
        sizeLimit: 64Mi
'''
    }
    if (dependencySet.contains('redis')) {
        dependencyContainers += '''
    - name: redis
      image: redis:8-alpine@sha256:becdda6c7f4b3fb42e42fd7f120bbf5c54c4caaaf16f26da24e4563d2c1f0576
      imagePullPolicy: IfNotPresent
      command: ["redis-server"]
      args: ["--save", "", "--appendonly", "no"]
      resources:
        requests:
          cpu: 50m
          memory: 64Mi
        limits:
          cpu: 500m
          memory: 256Mi
      securityContext:
        allowPrivilegeEscalation: false
        runAsNonRoot: true
        runAsUser: 999
        runAsGroup: 1000
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: redis-data
          mountPath: /data
        - name: redis-tmp
          mountPath: /tmp
'''
        dependencyVolumes += '''
    - name: redis-data
      emptyDir:
        sizeLimit: 256Mi
    - name: redis-tmp
      emptyDir:
        sizeLimit: 32Mi
'''
    }
    if (dependencySet.contains('kafka')) {
        dependencyContainers += '''
    - name: kafka
      image: apache/kafka:4.3.1@sha256:77e3df9054047a88b520d0cc46e16696d3b22022e1d580aeccd2632df6532837
      imagePullPolicy: IfNotPresent
      env:
        - name: KAFKA_NODE_ID
          value: "1"
        - name: KAFKA_PROCESS_ROLES
          value: broker,controller
        - name: KAFKA_LISTENERS
          value: PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
        - name: KAFKA_ADVERTISED_LISTENERS
          value: PLAINTEXT://localhost:9092
        - name: KAFKA_CONTROLLER_LISTENER_NAMES
          value: CONTROLLER
        - name: KAFKA_LISTENER_SECURITY_PROTOCOL_MAP
          value: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
        - name: KAFKA_CONTROLLER_QUORUM_VOTERS
          value: 1@localhost:9093
        - name: KAFKA_INTER_BROKER_LISTENER_NAME
          value: PLAINTEXT
        - name: KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR
          value: "1"
        - name: KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR
          value: "1"
        - name: KAFKA_TRANSACTION_STATE_LOG_MIN_ISR
          value: "1"
        - name: KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS
          value: "0"
        - name: KAFKA_LOG_DIRS
          value: /var/lib/kafka/data
      resources:
        requests:
          cpu: 250m
          memory: 512Mi
        limits:
          cpu: "1"
          memory: 1536Mi
      securityContext:
        allowPrivilegeEscalation: false
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: kafka-data
          mountPath: /var/lib/kafka/data
        - name: kafka-tmp
          mountPath: /tmp
'''
        dependencyVolumes += '''
    - name: kafka-data
      emptyDir:
        sizeLimit: 1Gi
    - name: kafka-tmp
      emptyDir:
        sizeLimit: 128Mi
'''
    }

    podTemplate(yaml: """
apiVersion: v1
kind: Pod
spec:
  serviceAccountName: faang-build-agent
  automountServiceAccountToken: false
  activeDeadlineSeconds: 2100
  nodeSelector:
    workload.faang.io/ci-heavy: "true"
    kubernetes.io/arch: amd64
  securityContext:
    fsGroup: 1000
    fsGroupChangePolicy: OnRootMismatch
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: jdk
      image: eclipse-temurin:25-jdk-alpine@sha256:09349d79941fd53bb3d487b393ca118d8853c08c09193f416fe6a8718df9e732
      imagePullPolicy: IfNotPresent
      command: ["sleep"]
      args: ["3600"]
      workingDir: /home/jenkins/agent
      env:
        - name: GRADLE_USER_HOME
          value: /home/jenkins/agent/.gradle${integrationEnvironment}
      resources:
        requests:
          cpu: 250m
          memory: 768Mi
        limits:
          cpu: "2"
          memory: 3Gi
      securityContext:
        allowPrivilegeEscalation: false
        runAsUser: 1000
        runAsGroup: 1000
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - name: untrusted-gradle-cache
          mountPath: /home/jenkins/agent/.gradle
${dependencyContainers}  volumes:
    - name: untrusted-gradle-cache
      emptyDir:
        sizeLimit: 2Gi
${dependencyVolumes}""") {
        node(POD_LABEL) {
            timeout(time: 30, unit: 'MINUTES') {
                stage('Checkout') {
                    deleteDir()
                    checkout scm
                }

                stage('Validate wrapper') {
                    container('jdk') {
                        sh '''
                            test -x ./gradlew
                            test -f gradle/wrapper/gradle-wrapper.jar
                            test -f gradle/wrapper/gradle-wrapper.properties
                            ./gradlew --version --no-daemon
                        '''
                    }
                }

                if (!dependencySet.isEmpty()) {
                    stage('Wait for disposable dependencies') {
                        if (dependencySet.contains('postgres')) {
                            container('jdk') {
                                sh 'for attempt in $(seq 1 120); do nc -z 127.0.0.1 5432 && exit 0; sleep 1; done; exit 1'
                            }
                        }
                        if (dependencySet.contains('redis')) {
                            container('jdk') {
                                sh 'for attempt in $(seq 1 120); do nc -z 127.0.0.1 6379 && exit 0; sleep 1; done; exit 1'
                            }
                        }
                        if (dependencySet.contains('kafka')) {
                            container('jdk') {
                                sh 'for attempt in $(seq 1 180); do nc -z 127.0.0.1 9092 && exit 0; sleep 1; done; exit 1'
                            }
                        }
                    }
                }

                stage('Compile, test, coverage, and integration') {
                    container('jdk') {
                        try {
                            sh "./gradlew ${taskArguments} --no-daemon --stacktrace"
                        } finally {
                            archiveArtifacts(
                                artifacts: 'build/test-results/**/*.xml,build/reports/**',
                                allowEmptyArchive: true,
                                fingerprint: true
                            )
                        }
                    }
                }
            }
        }
    }
}
